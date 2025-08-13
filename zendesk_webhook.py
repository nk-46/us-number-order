#!/usr/bin/env python3
"""
Zendesk Webhook Server
Handles incoming Zendesk ticket updates and processes number requests.

ADDITIVE CHANGES:
- Health monitoring endpoints (/health, /metrics)
- Enhanced Redis error handling
- Backorder tracking integration
"""

import os
import json
import logging
import sqlite3
import redis
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import requests
import time
import uuid
from filelock import FileLock, Timeout

# Import core functionality
from main import handle_user_request
from backorder_tracker import get_backorder_tracker

app = Flask(__name__)

# -------------------------
# 🔐 Zendesk Credentials
# -------------------------
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_TOKEN = os.getenv("ZENDESK_TOKEN")
DB_NAME = '/data/zendesk_tickets.db'

# Handle local development environment
if not os.path.exists("/data") and os.path.exists("data"):
    DB_NAME = "data/zendesk_tickets.db"

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

# -------------------------
# 📋 Logging Setup
# -------------------------
LOG_FILE = "/data/us_ca_lc.log"

# Handle local development environment
try:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )
except FileNotFoundError:
    # Fallback for local development
    LOG_FILE = "data/us_ca_lc.log"
    os.makedirs("data", exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )

logger = logging.getLogger(__name__)

TICKET_TAGS = ["support_automation", "us_number_order_ai_automation"]

# -------------------------
# 🔖 Tag Ticket Immediately
# -------------------------
def tag_ticket_immediately(ticket_id, new_tag=TICKET_TAGS):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
    headers = {"Content-Type": "application/json"}

    try:
        get_response = requests.get(url, auth=auth, headers=headers)
        if get_response.status_code != 200:
            logger.error(f"⚠️ Failed to fetch ticket {ticket_id} for tagging")
            return

        existing_tags = get_response.json().get("ticket", {}).get("tags", [])
        updated_tags = list(set(existing_tags + new_tag))

        patch_payload = {"ticket": {"tags": updated_tags}}
        patch_response = requests.put(url, json=patch_payload, auth=auth, headers=headers)

        if patch_response.status_code in [200, 201]:
            logger.info(f"✅ Tags updated on ticket #{ticket_id}")
        else:
            logger.error(f"❌ Tag update failed: {patch_response.status_code} - {patch_response.text}")
    except Exception as e:
        logger.exception(f"❌ Exception tagging ticket #{ticket_id}: {e}")

# -------------------------
# 📝 Post Comment to Zendesk
# -------------------------
def post_zendesk_comment(ticket_id, internal_comment, public_comment=None, new_tag=TICKET_TAGS, prefix=None):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
    headers = {"Content-Type": "application/json"}

    try:
        get_response = requests.get(url, auth=auth, headers=headers)
        if get_response.status_code != 200:
            logger.error(f"⚠️ Failed to fetch ticket for comment update")
            return

        existing_tags = get_response.json().get("ticket", {}).get("tags", [])
        updated_tags = list(set(existing_tags + new_tag))

        shared_custom_fields = [
            {"id": 360035634992, "value": "carrier_ticket_no"},
            {"id": 38226917914265, "value": "us_longcodes"},
            {"id": 38227031586841, "value": "number_order__"},
            {"id": 360035174572, "value": prefix}
        ]

        internal_payload = {
            "ticket": {
                "comment": {"body": internal_comment, "public": False},
                "status": "open",
                "tags": updated_tags,
                "custom_fields": shared_custom_fields
            }
        }

        response = requests.put(url, json=internal_payload, auth=auth, headers=headers)
        if response.status_code in [200, 201]:
            logger.info(f"✅ Internal comment posted on ticket #{ticket_id}")
        else:
            logger.error(f"❌ Failed to post internal comment: {response.status_code} - {response.text}")
    except Exception as e:
        logger.exception(f"❌ Error posting internal comment: {e}")

    if public_comment:
        try:
            public_payload = {
                "ticket": {
                    "comment": {"body": public_comment, "public": False},
                    "tags": updated_tags,
                    "custom_fields": shared_custom_fields
                }
            }
            response = requests.put(url, json=public_payload, auth=auth, headers=headers)
            if response.status_code in [200, 201]:
                logger.info(f"✅ Public comment posted on ticket #{ticket_id}")
            else:
                logger.error(f"❌ Failed to post public comment: {response.status_code} - {response.text}")
        except Exception as e:
            logger.exception(f"❌ Error posting public comment: {e}")

# -------------------------
# 🧱 Initialize DB
# -------------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER UNIQUE,
            subject TEXT,
            body TEXT,
            processed INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

# -------------------------

# 🏠 Root Endpoint
# -------------------------
@app.route('/', methods=['GET'])
def root():
    """Simple root endpoint for basic health checks"""
    return jsonify({
        "status": "running",
        "service": "us-number-order-webhook",
        "timestamp": datetime.now().isoformat()
    }), 200

# -------------------------

# 🏥 Health Check Endpoint
# -------------------------
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Check database connectivity
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tickets")
        ticket_count = cursor.fetchone()[0]
        conn.close()
        
        # Check Redis connectivity
        redis_ping = redis_client.ping()
        
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": "connected",
            "redis": "connected" if redis_ping else "disconnected",
            "ticket_count": ticket_count,
            "version": "1.0.0"
        }
        
        return jsonify(health_status), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

# -------------------------
# 📊 Metrics Endpoint
# -------------------------
@app.route('/metrics', methods=['GET'])
def metrics():
    """Metrics endpoint for monitoring system performance"""
    try:

        # Get basic metrics
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tickets")
        total_tickets = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE processed = 1")
        processed_tickets = cursor.fetchone()[0]
        conn.close()
        
        metrics_data = {
            "total_tickets": total_tickets,
            "processed_tickets": processed_tickets,
            "pending_tickets": total_tickets - processed_tickets,
            "timestamp": datetime.now().isoformat()

        # Database metrics
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Get ticket statistics
        cursor.execute("SELECT COUNT(*) FROM tickets")
        total_tickets = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE processed = 1")
        processed_tickets = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE processed = 0")
        pending_tickets = cursor.fetchone()[0]
        
        # Note: created_at column doesn't exist in current schema
        # Using total tickets as recent activity for now
        recent_tickets = total_tickets
        
        conn.close()
        
        # Redis metrics
        redis_info = redis_client.info()
        
        metrics_data = {
            "tickets": {
                "total": total_tickets,
                "processed": processed_tickets,
                "pending": pending_tickets,
                "recent_24h": recent_tickets
            },
            "redis": {
                "connected_clients": redis_info.get('connected_clients', 0),
                "used_memory": redis_info.get('used_memory_human', '0B'),
                "uptime": redis_info.get('uptime_in_seconds', 0)
            },
            "system": {
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0"
            }

        }
        
        return jsonify(metrics_data), 200
        
    except Exception as e:
        logger.error(f"Metrics endpoint failed: {e}")

        return jsonify({
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

# -------------------------
# 📥 Webhook Endpoint
# -------------------------
@app.route('/zendesk-webhook', methods=['POST'])
def zendesk_webhook():
    request_id = str(uuid.uuid4())
    logger.info(f"🔁 Webhook triggered: {request_id}")

    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "Invalid JSON"}), 400

    ticket = data.get("ticket") or {}
    ticket_id = ticket.get("id") or data.get("ticket_id")
    subject = ticket.get("subject") or data.get("subject", "")
    description = ticket.get("description") or data.get("description", "")
    status = ticket.get("status", "").lower()

    if not ticket_id:
        return jsonify({"error": "Missing ticket ID"}), 400
    if status == "hold":
        return jsonify({"status": "ignored - on hold"}), 200

    ticket_lock_path = f"/tmp/ticket_{ticket_id}.lock"
    file_lock = FileLock(ticket_lock_path, timeout=1)

    redis_lock_key = f"lock:ticket:{ticket_id}"
    redis_lock = redis_client.lock(redis_lock_key, timeout=30, blocking_timeout=1)

    try:
        with file_lock, redis_lock:
            logger.info(f"🔐 Acquired file + redis lock for ticket {ticket_id}")

            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT processed FROM tickets WHERE ticket_id = ?", (ticket_id,))
            row = cursor.fetchone()
            conn.close()

            if row and row[0] == 1:
                logger.info(f"⛔ Already processed ticket #{ticket_id}")
                return jsonify({"status": "already processed"}), 200

            # DB insert
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO tickets (ticket_id, subject, body)
                VALUES (?, ?, ?)
            ''', (ticket_id, subject, description))
            conn.commit()
            conn.close()

            prompt = f"{subject.strip()}\n\n{description.strip()}"
            ai_output = handle_user_request(prompt, ticket_id=ticket_id)

            if ai_output.get("skip_update"):
                logger.info(f"⏭️ Skipping tag update for ticket #{ticket_id} - not a number request")
                return jsonify({"status": "ignored - not a number request"}), 200

            # Only tag the ticket if it's a number request
            tag_ticket_immediately(ticket_id)

            ai_output_str = json.dumps(ai_output, indent=2)

            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE tickets
                SET body = body || "\n\n---- Assistant response: \n" || ?, processed = 1
                WHERE ticket_id = ?
            ''', (ai_output_str, ticket_id))
            conn.commit()
            conn.close()

            post_zendesk_comment(
                ticket_id,
                internal_comment=ai_output["internal"],
                public_comment=ai_output["public"],
                prefix=ai_output["prefix"]
            )

            time.sleep(30)
            return jsonify({"status": "success"}), 200

    except Timeout:
        logger.warning(f"⏳ Ticket {ticket_id} already locked and being processed.")
        return jsonify({"status": "skipped - lock held elsewhere"}), 200
    except redis.exceptions.LockNotOwnedError as e:
        logger.warning(f"🔓 Redis lock already released for ticket {ticket_id}: {e}")
        return jsonify({"status": "skipped - lock expired"}), 200
    except Exception as e:
        logger.exception(f"❌ Error during processing: {e}")
        return jsonify({"status": "error"}), 500

# -------------------------
# 🚀 App Runner
# -------------------------
if __name__ == '__main__':
    init_db()
    logger.info("🚀 Flask server running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000)
