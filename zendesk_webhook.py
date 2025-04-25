from flask import Flask, request, jsonify
import sqlite3
import requests
import os
import time
import json
import uuid
import logging
from main import handle_user_request, run_assistant_with_input, search_iq_inventory, search_plivo_numbers, order_reserved_numbers, retrieve_reserved_iq

app = Flask(__name__)

#Zendesk details
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_TOKEN = os.getenv("ZENDESK_TOKEN")

DB_NAME = '/data/zendesk_tickets.db'

# Configure logging
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

def post_zendesk_comment(ticket_id, internal_comment, public_comment= None, new_tag=["us_number_order_ai_automation", "support_automation"],prefix=None):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
    headers = {
        "Content-Type": "application/json"
    }

    # Step 1: Fetch existing ticket tags
    try:
        get_response = requests.get(url, auth=auth, headers=headers)
        logger.info(f"Zendesk response: {get_response}")
        if get_response.status_code not in [200, 201]:
            print(f"⚠️ Failed to fetch ticket details: {get_response.status_code}")
            logger.infoprint(f"⚠️ Failed to fetch ticket details: {get_response.status_code}")
            return

        ticket_data = get_response.json().get("ticket", {})
        existing_tags = ticket_data.get("tags", [])
        print(f"🔖 Current tags: {existing_tags}")

        # Add new tag if not already present
        if new_tag not in existing_tags:
            existing_tags.extend(new_tag)

    except Exception as e:
        print(f"❌ Error fetching ticket tags: {e}")
        return

    # Step 2: Update ticket with comment + updated tags
    internal_payload = {
        "ticket": {
            "comment": {
                "body": internal_comment,
                "public": False
            },
            "status": "open",
            "tags": existing_tags,
            "custom_fields" : [
                {
                    "id" : 360035634992, #carrier ticket
                    "value" : "carrier_ticket_no"
                },
                {
                    "id" : 38226917914265, #Phone numbers type(internal)
                    "value" : "us_longcodes"
                },
                {
                    "id" : 38227031586841, #Us/ca longcodes type
                    "value" : "number_order__"
                },
                {
                    "id" : 360035174572, #Prefix
                    "value" : prefix
                }
            ]
        }
    }

    try:
        put_response = requests.put(url, json=internal_payload, auth=auth, headers=headers)
        if put_response.status_code in [200, 201]:
            print(f"✅ Posted comment and updated tags on Zendesk ticket #{ticket_id}")
            logger.info(f"✅ Posted comment and updated tags on Zendesk ticket #{ticket_id}")
        else:
            print(f"❌ Failed to update Zendesk ticket: {put_response.status_code} - {put_response.text}")
            logger.info(f"❌ Failed to update Zendesk ticket: {put_response.status_code} - {put_response.text}")
    except Exception as e:
        print(f"❌ Error updating Zendesk ticket: {e}")
        logger.info(f"❌ Error updating Zendesk ticket: {e}")

    #Step 3: Post public comment if provided
    if public_comment:
        public_payload = {
            "ticket": {
                "comment": {
                    "body": public_comment,
                    "public": False   #will be changed to True in production.
                },
                "tags": existing_tags,
                "custom_fields" : [
                {
                    "id" : 360035634992, #carrier ticket
                    "value" : "carrier_ticket_no"
                },
                {
                    "id" : 38226917914265, #Phone numbers type(internal)
                    "value" : "us_longcodes"
                },
                {
                    "id" : 38227031586841, #Us/ca longcodes type
                    "value" : "number_order__"
                },
                {
                    "id" : 360035174572, #Prefix
                    "value" : prefix
                }
            ]
            }
        }
        try:
            response = requests.put(url, json=public_payload, auth=auth, headers=headers)
            if response.status_code in [200, 201]:
                print(f"✅ Public comment posted to Zendesk ticket #{ticket_id}")
                logger.info(f"✅ Public comment posted to Zendesk ticket #{ticket_id}")
            else:
                print(f"❌ Failed to post public comment: {response.status_code} - {response.text}")
                logger.info(f"❌ Failed to post public comment: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Error posting public comment: {e}")
            logger.info(f"❌ Error posting public comment: {e}")





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
    print(f"🔁 Webhook request ID: {request_id}")
    print("\n📥 New webhook hit!")
    print("🔎 Headers:", dict(request.headers))
    print("📦 Raw Body:", request.data.decode())

    # Attempt to parse JSON payload
    try:
        data = request.get_json(force=True)
        print("✅ Parsed JSON:", data)
    except Exception as e:
        print("❌ JSON parsing error:", e)
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    # Validate ticket data (supports nested and flat formats)
    ticket = data.get("ticket")
    if ticket:
        ticket_id = ticket.get("id")
        subject = ticket.get("subject", "")
        description = ticket.get("description", "")
        ticket_status = ticket.get("status", "")

        if ticket_status.lower() == "hold":
            print(f"🚫 Skipping ticket #{ticket_id} - status is '{ticket_status}'")
            return jsonify({"status": "ignored"}), 200

    else:
        # Handle flat test payload
        ticket_id = data.get("ticket_id")
        subject = data.get("subject", "")
        description = data.get("description", "")

    if not ticket_id:
        print("❌ Missing ticket_id")
        return jsonify({"error": "Missing ticket ID"}), 400

    # ✅ Check if already processed
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT processed FROM tickets WHERE ticket_id = ?", (ticket_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] == 1:
        print(f"⛔ Ticket #{ticket_id} already processed. Skipping.")
        return jsonify({"status": "already processed"}), 200
    # Insert into DB
    try:
        db_path = os.path.abspath(DB_NAME)
        print(f"💾 Writing to DB at: {db_path}")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO tickets (ticket_id, subject, body)
            VALUES (?, ?, ?)
        ''', (ticket_id, subject, description))

        conn.commit()
        conn.close()

        print("✅ Ticket stored successfully.")

        #Using ZD description to run the flow
        try:
            print("Triggering assistant flow in real time")
            ai_output = handle_user_request(description,ticket_id=ticket_id)
            if ai_output:
                #update the ticket with assitant output
                ai_output_str = json.dumps(ai_output, indent= 2)
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute('''
                            UPDATE tickets
                               SET body = body || "\n\n ---- Assistant response: \n" || ?
                               WHERE ticket_id = ?
                    ''', (ai_output_str, ticket_id))
                conn.commit()
                conn.close()
                print("Assitant output saved to DB.")

                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute("UPDATE tickets SET processed = 1 WHERE ticket_id = ?", (ticket_id,))
                conn.commit()
                conn.close()


            #Post internal comment to zendesk
            post_zendesk_comment(ticket_id, internal_comment= ai_output["internal"], public_comment=ai_output["public"], prefix=ai_output["prefix"])
            time.sleep(30) #pausing the execution to prevent the ZD trigger to run multiple times
            

        except Exception as e:
            print(f"error during assistant handling {e}")
            return jsonify({"status" : "ticket stored, assistant failed"}), 200
        return jsonify({"status": "success"}), 200

    except Exception as e:
        print("❌ DB error:", e)
        return jsonify({"error": str(e)}), 500


# -------------------------
# 🚀 App Runner
# -------------------------
if __name__ == '__main__':
    init_db()
    print("🚀 Flask server running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000)
