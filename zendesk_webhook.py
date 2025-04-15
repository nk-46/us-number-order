from flask import Flask, request, jsonify
import sqlite3
import requests
import os
from main import handle_user_request, run_assistant_with_input, search_iq_inventory, search_plivo_numbers, order_reserved_numbers, retrieve_reserved_iq

app = Flask(__name__)

#Zendesk details
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_TOKEN = os.getenv("ZENDESK_TOKEN")

DB_NAME = 'zendesk_tickets.db'

def post_zendesk_comment(ticket_id, comment, new_tag="us_number_order_ai_automation"):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
    headers = {
        "Content-Type": "application/json"
    }

    # Step 1: Fetch existing ticket tags
    try:
        get_response = requests.get(url, auth=auth, headers=headers)
        if get_response.status_code not in [200, 201]:
            print(f"⚠️ Failed to fetch ticket details: {get_response.status_code}")
            return

        ticket_data = get_response.json().get("ticket", {})
        existing_tags = ticket_data.get("tags", [])
        print(f"🔖 Current tags: {existing_tags}")

        # Add new tag if not already present
        if new_tag not in existing_tags:
            existing_tags.append(new_tag)

    except Exception as e:
        print(f"❌ Error fetching ticket tags: {e}")
        return

    # Step 2: Update ticket with comment + updated tags
    payload = {
        "ticket": {
            "comment": {
                "body": comment,
                "public": False
            },
            "tags": existing_tags
        }
    }

    try:
        put_response = requests.put(url, json=payload, auth=auth, headers=headers)
        if put_response.status_code in [200, 201]:
            print(f"✅ Posted comment and updated tags on Zendesk ticket #{ticket_id}")
        else:
            print(f"❌ Failed to update Zendesk ticket: {put_response.status_code} - {put_response.text}")
    except Exception as e:
        print(f"❌ Error updating Zendesk ticket: {e}")





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
            body TEXT
        )
    ''')
    conn.commit()
    conn.close()


# -------------------------
# 📥 Webhook Endpoint
# -------------------------
@app.route('/zendesk-webhook', methods=['POST'])
def zendesk_webhook():
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
    else:
        # Handle flat test payload
        ticket_id = data.get("ticket_id")
        subject = data.get("subject", "")
        description = data.get("description", "")

    if not ticket_id:
        print("❌ Missing ticket_id")
        return jsonify({"error": "Missing ticket ID"}), 400


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
            ai_output = handle_user_request(description)
            if ai_output:
                #update the ticket with assitant output
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute('''
                            UPDATE tickets
                               SET body = body || "\n\n ---- Assistant response: \n" || ?
                               WHERE ticket_id = ?
                    ''', (ai_output, ticket_id))
                conn.commit()
                conn.close()
                print("Assitant output saved to DB.")

            #Post internal comment to zendesk
            post_zendesk_comment(ticket_id, ai_output)

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
