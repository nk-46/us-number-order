from flask import Flask, request, jsonify
import sqlite3
import requests
import os
import time
import json
import uuid
import logging
from main import (
    handle_user_request,
    run_assistant_with_input,
    search_iq_inventory,
    search_plivo_numbers,
    order_reserved_numbers,
    retrieve_reserved_iq
)

app = Flask(__name__)

# -------------------------
# 🔐 Zendesk Credentials
# -------------------------
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_TOKEN = os.getenv("ZENDESK_TOKEN")
DB_NAME = '/data/zendesk_tickets.db'

# -------------------------
# 📋 Logging Setup
# -------------------------
LOG_FILE = "/data/us_ca_lc.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TICKET_TAGS = ["support-automation", "us_number_order_ai_automation"]

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
                    "comment": {"body": public_comment, "public": True},
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
# 📥 Webhook Endpoint
# -------------------------
@app.route('/zendesk-webhook', methods=['POST'])
def zendesk_webhook():
    request_id = str(uuid.uuid4())
    logger.info(f"🔁 Webhook triggered: {request_id}")

    try:
        data = request.get_json(force=True)
        logger.debug(f"📦 Payload: {data}")
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

    # Check DB to prevent reprocessing
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT processed FROM tickets WHERE ticket_id = ?", (ticket_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] == 1:
        logger.info(f"⛔ Already processed ticket #{ticket_id}")
        return jsonify({"status": "already processed"}), 200

    try:
        # Write to DB
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO tickets (ticket_id, subject, body)
            VALUES (?, ?, ?)
        ''', (ticket_id, subject, description))
        conn.commit()
        conn.close()
        logger.info(f"💾 Ticket #{ticket_id} written to DB")

        # Tag immediately to block further triggers
        tag_ticket_immediately(ticket_id)

        # Run assistant
        prompt = f"{subject.strip()}\n\n{description.strip()}"
        ai_output = handle_user_request(prompt, ticket_id=ticket_id)

        if ai_output.get("skip_update"):
            logger.info(f"🛑 Assistant skipped update for #{ticket_id}")
            return jsonify({"status": "ignored - not a number request"}), 200

        # Store response in DB
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

        # Post to Zendesk
        post_zendesk_comment(
            ticket_id,
            internal_comment=ai_output["internal"],
            public_comment=ai_output["public"],
            prefix=ai_output["prefix"]
        )

        time.sleep(30)  # Delay to prevent back-to-back hits if needed
        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.exception(f"❌ Exception during webhook processing: {e}")
        return jsonify({"status": "ticket stored, assistant failed"}), 200

# -------------------------
# 🚀 App Runner
# -------------------------
if __name__ == '__main__':
    init_db()
    logger.info("🚀 Flask server running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000)
