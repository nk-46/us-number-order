import os
import re
import time
import base64
import requests
import logging
import json
from dotenv import load_dotenv
from openai import OpenAI
from plivo import RestClient
from collections import defaultdict
import phonenumbers
from phonenumbers import parse, NumberParseException, region_code_for_number, geocoder
from plivo import RestClient

from dotenv import load_dotenv
load_dotenv()

# --------------------------- SETUP CLIENTS ---------------------------
# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PROJECT_ID = os.getenv("OPENAI_PROJECT_ID")
openai_client = OpenAI(api_key=OPENAI_API_KEY, project=PROJECT_ID)
ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
THREAD_ID = os.getenv("OPENAI_THREAD_ID")
iq_trunk_group = os.getenv("IQ_TRUNK_GROUP")

# Plivo
PLIVO_AUTH_ID = os.getenv("PLIVO_AUTH_ID")
PLIVO_AUTH_TOKEN = os.getenv("PLIVO_AUTH_TOKEN")
client = RestClient(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN)

# Inteliquent
iq_access_token = os.getenv("IQ_ACCESS_TOKEN")
iq_private_key = os.getenv("IQ_PRIVATE_KEY")
iq_secret_key = os.getenv("IQ_SECRET_KEY")
iq_api_base_url = "https://services.inteliquent.com/Services/2.0.0"
search_inventory_endpoint = "/tnInventory"
reserve_number_endpoint = "/tnReserve"
retrieve_reserved_number_endpoint = "/tnReservedList"
order_iq_reserved_endpoint = "/tnOrder"
request_iq_number_endpoint = "/tnRequest"

# Encode inteliquent credentials to Base64
credentials = f"{iq_private_key}:{iq_secret_key}"
encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

iq_headers = {
    "Authorization": f"Basic {encoded_credentials}",
    "Content-Type": "application/json"
}

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

# --- CORE FUNCTION: run OpenAI assistant ---
def run_assistant_with_input(assistant_id, thread_id, user_message):
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), project=os.getenv("OPENAI_PROJECT_ID"))

    openai_client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_message)

    run = openai_client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)

    while True:
        run_status = openai_client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        if run_status.status == "completed":
            break
        elif run_status.status in ["failed", "cancelled", "expired"]:
            raise Exception(f"Assistant run failed with status: {run_status.status}")
        time.sleep(1)

    messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
    for msg in reversed(messages.data):
        if msg.role == "assistant":
            return msg.content[0].text.value
    return None

# --- SEARCH FUNCTIONS ---

def search_plivo_numbers(numbers, number_with_area_code, area_code, region, type_="local", limit=2):
    if not numbers:
        logger.warning("Skipping Plivo search: 'numbers' is empty.")
        return []

    raw_pattern = number_with_area_code.strip() if number_with_area_code and number_with_area_code.strip() else area_code.strip()
    pattern = raw_pattern[1:] if raw_pattern.startswith("1") else raw_pattern
    country_iso = region if region in ["US", "CA"] else "US"

    collected = []
    offset = 0
    page_size = 20

    try:
        while len(collected) < limit:
            response = client.numbers.search(
                country_iso=country_iso,
                type=type_,
                pattern=pattern,
                services=None,
                limit=min(page_size, limit - len(collected)),
                offset=offset
            )
            batch = response.objects
            collected.extend(batch)

            if not batch or len(batch) < page_size:
                break
            offset += page_size

        return collected[:limit]

    except Exception as e:
        logger.error(f"Error paginating Plivo search for pattern {pattern}: {str(e)}")
        return []

def search_iq_inventory(payload, endpoint="/tnInventory", method='POST'):
    url = f"{iq_api_base_url}{endpoint}"
    if method.upper() == 'POST':
        response = requests.post(url, json=payload, headers=iq_headers)
    else:
        raise ValueError(f"Unsupported method: {method}")
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")

def retrieve_reserved_iq(payload, endpoint="/tnReservedList"):
    url = f"{iq_api_base_url}{endpoint}"
    response = requests.post(url, json=payload, headers=iq_headers)
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")

def order_reserved_numbers(reserved_tns, private_key, trunk_group, endpoint="/tnOrder"):
    url = f"{iq_api_base_url}{endpoint}"
    payload = {
        "privateKey": private_key,
        "tnOrder": {
            "tnList": {
                "tnItem": [{"tn": tn.get("tn"), "trunkGroup": trunk_group} for tn in reserved_tns if tn.get("tn")]
            }
        }
    }
    response = requests.post(url, json=payload, headers=iq_headers)
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")

def place_inteliquent_backorder(ticket_id, npa, trunk_group, activate="N", endpoint="/tnRequest"):
    url = f"{iq_api_base_url}{endpoint}"
    payload = {
        "privateKey": iq_private_key,
        "customerOrderReference": str(ticket_id),
        "npa": npa,
        "trunkGroup": trunk_group,
        "activate": activate
    }
    response = requests.post(url, json=payload, headers=iq_headers)
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")

# --- FALLBACK LOGIC ---

def fallback_number_search(search_key, quantity, ticket_id=None):
    results_text = ""
    incomplete_log = {
        "prefix": search_key,
        "plivo_count": 0,
        "fallback_used": False,
        "backorder_id": None
    }

    try:
        dummy_number = f"+1{search_key}5551234"
        num = parse(dummy_number, "US")
        region = region_code_for_number(num)
    except NumberParseException:
        logger.warning(f"❌ Invalid prefix skipped: {search_key}")
        return "", incomplete_log

    plivo_result = search_plivo_numbers(["dummy"], search_key, search_key, region, limit=quantity)

    if plivo_result:
        results_text += f"\n\n📞 Plivo numbers for {search_key}:\n"
        for r in plivo_result:
            results_text += f" - {r['number']}\n"
        incomplete_log["plivo_count"] = len(plivo_result)

        if len(plivo_result) >= quantity:
            return results_text, incomplete_log

        results_text += f"⚠️ Only {len(plivo_result)} found in Plivo. Trying Inteliquent...\n"

    tn_mask = f"{search_key}{'x' * (10 - len(search_key))}"
    iq_payload = {
        "privateKey": iq_private_key,
        "tnMask": tn_mask,
        "quantity": quantity,
        "reserve": "Y"
    }

    iq_response = search_iq_inventory(iq_payload)
    status_code = iq_response.get("statusCode")
    iq_results = iq_response.get("tnResult", [])

    if status_code == "430":
        if ticket_id:
            try:
                backorder_response = place_inteliquent_backorder(ticket_id, search_key, iq_trunk_group)
                order_id = backorder_response.get("orderId", "N/A")
                logger.info(f"backorder response:\n{backorder_response}")
                results_text += f"\n📦 Backorder placed. Order ID: {order_id}\n"
                incomplete_log["backorder_id"] = order_id
                incomplete_log["fallback_used"] = True
            except Exception as e:
                results_text += f"\n⚠️ Backorder failed: {e}\n"
        return results_text, incomplete_log

    if iq_results:
        results_text += f"\n\n📞 Inteliquent numbers for {search_key}:\n"
        for tn in iq_results[:quantity]:
            results_text += f" - {tn['telephoneNumber']} ({tn['city']}, {tn['province']})\n"

        retrieve_payload = {"privatekey": iq_private_key}
        reserved_data = retrieve_reserved_iq(payload=retrieve_payload)
        reserved_tns = reserved_data.get("reservedTns", [])

        if reserved_tns:
            results_text += f"\n✅ Reserved numbers:\n"
            for tn in reserved_tns:
                results_text += f" - {tn.get('telephoneNumber')}\n"

            order_response = order_reserved_numbers(reserved_tns, iq_private_key, iq_trunk_group)
            results_text += f"\n📦 Order placed:\n{json.dumps(order_response, indent=2)}\n"

    return results_text, incomplete_log

# --- MAIN ENTRYPOINT ---

def handle_user_request(user_input, ticket_id=None):
    ai_response = run_assistant_with_input(ASSISTANT_ID, THREAD_ID, user_input)
    full_output = f"Assistant Response:\n{ai_response}\n\n"
    if not ai_response:
        print("No AI response found.")
        return

    try:
        response_data = json.loads(ai_response)
        numbers_list = response_data.get("numbers", [])
    except Exception as e:
        print(f"❌ Failed to parse AI response as JSON: {e}")
        return f"{full_output} Failed to extract number patterns from assistant's response"

    results_text = ""
    searched_keys = set()
    incomplete_results = []

    for entry in numbers_list:
        quantity = entry.get("quantity", 1)
        area_code = entry.get("area_code", "").strip()
        with_area = entry.get("number_with_area_code", "").strip()
        search_key = with_area or area_code

        if not search_key or search_key in searched_keys:
            continue
        searched_keys.add(search_key)

        partial_text, log_entry = fallback_number_search(search_key, quantity, ticket_id)
        results_text += partial_text
        if log_entry["plivo_count"] < quantity:
            incomplete_results.append(log_entry)

    if incomplete_results:
        print("📉 Incomplete search logs:")
        for item in incomplete_results:
            logger.warning(f"🔸 {item}")

    return full_output + results_text.strip()



if __name__ == "__main__":
    USER_INPUT = """
I need 5 numbers with area code 360

"""
    handle_user_request(USER_INPUT)