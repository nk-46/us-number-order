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

# Load environment variables
load_dotenv(override=True)

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
LOG_FILE = "us_ca_lc.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --------------------------- UTILITY FUNCTIONS ---------------------------

def search_iq_inventory(payload, endpoint=search_inventory_endpoint, method='POST'):
    url = f"{iq_api_base_url}{endpoint}"
    if method.upper() == 'POST':
        response = requests.post(url, json=payload, headers=iq_headers)
    else:
        raise ValueError(f"Unsupported method: {method}")
    
    if response.status_code in [200, 201]:
        logger.info(f"IQ RESPONSE: {response.json()}")
        return response.json()
    else:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")
    

    #Note: This function is commented out because the reserving the numbers option is available in the search inventory API itself.
"""def reserve_iq_numbers(payload, endpoint = reserve_number_endpoint, method = 'POST'):
    url = f"{iq_api_base_url}{endpoint}"
    if method.upper() == "POST":
        response = requests.post(url, json = payload, headers=iq_headers)
    else:
        raise ValueError(f"Unsupported method: {method}")
    
    if response.status_code in [200,201]:
        logger.info(f"IQ Reserver response: {response.json()}")
        return response.json()
    else:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")"""
    

def retrieve_reserved_iq(payload, endpoint = retrieve_reserved_number_endpoint, method = "POST"):
    url = f"{iq_api_base_url}{retrieve_reserved_number_endpoint}"
    payload = {
        "privateKey": iq_private_key
    }
    if method.upper() == "POST":
        response = requests.post(url, json = payload, headers=iq_headers)
    else:
        raise ValueError(f"Unsupported menthod: {method}")
    
    if response.status_code in [200, 201]:
        logger.info(f"Reserved numbers retrieval completed: {response.json()}")
        print(f"Reserved Numbers list retrieved:\n{response.json()}")
        return response.json()
    else:
        raise Exception(f" API call failed: {response.status_code} = {response.text}")


def order_reserved_numbers(reserved_tns, private_key= iq_private_key, trunk_group= iq_trunk_group, endpoint="/tnOrder", method="POST"):
    url = f"{iq_api_base_url}{endpoint}"
    
    payload = {
        "privateKey": private_key,
        "tnOrder": {
            "tnList": {
                "tnItem": [
                    {
                        "tn": tn.get("telephoneNumber"),
                        "trunkGroup": trunk_group
                    } for tn in reserved_tns if "telephoneNumber" in tn
                ]
            }
        }
    }

    # Log the payload for debugging
    logger.debug("📦 Order payload:\n" + json.dumps(payload, indent=2))

    if method.upper() == "POST":
        response = requests.post(url, json=payload, headers=iq_headers)
    else:
        raise ValueError(f"Unsupported method: {method}")

    if response.status_code in [200, 201]:
        logger.info("✅ Number order placed successfully.")
        logger.info(f"{response.json()}")
        return response.json()
    else:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")

def place_inteliquent_backorder(
    npa: str,
    trunk_group: str,
    activate: str = "Y",
    endpoint: str = request_iq_number_endpoint,
    quantity: str = ""
) -> dict:
    """
    Place a backorder request to Inteliquent using the TN Request API when no inventory is found.

    Args:
        ticket_id (int): Zendesk ticket ID (used as customerOrderReference)
        npa (str): Area code / NPA prefix
        trunk_group (str): Assigned Trunk Group
        activate (str): 'Y' or 'N' — whether to activate immediately (default: 'N')
        endpoint (str): API endpoint to hit (default: /tnRequest)

    Returns:
        dict: Full JSON response from the Inteliquent API
    """
    url = f"{iq_api_base_url}{endpoint}"

    payload = {
        "privateKey": iq_private_key,
        "npa": npa,
        "trunkGroup": trunk_group,
        "activate": activate,
        "quantity" : quantity
    }

    logger.debug("📦 TN Request Payload:\n" + json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload, headers=iq_headers)
        if response.status_code in [200, 201]:
            logger.info(f"✅ Backorder placed for NPA {npa}.")
            return response.json()
        else:
            raise Exception(f"API call failed: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"❌ Error placing TN request for {npa}: {e}")
        raise


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

# --------------------------- OPENAI ASSISTANT FLOW ---------------------------

def run_assistant_with_input(assistant_id, thread_id, user_message):
    print("📨 Sending user message...")
    openai_client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_message
    )

    print("⚙️  Running assistant...")
    run = openai_client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id
    )

    while True:
        run_status = openai_client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        if run_status.status == "completed":
            break
        elif run_status.status in ["failed", "cancelled", "expired"]:
            raise Exception(f"❌ Assistant run failed with status: {run_status.status}")
        time.sleep(1)

    print("📬 Fetching assistant response...")
    messages = openai_client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id)
    
    for msg in reversed(messages.data):
        if msg.role == "assistant":
            content = msg.content[0].text.value
            print("\n🤖 Assistant Response:")
            logger.info("\nAssistant response:")
            logger.info(content)
            print(content)
            return content
    return None

# --------------------------- PARSE AND SEARCH FLOW ---------------------------

def handle_user_request(user_input):
    ai_response = run_assistant_with_input(ASSISTANT_ID, THREAD_ID, user_input)
    full_output = f"Assitant Response:\n{ai_response}\n\n"
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

    for entry in numbers_list:
        quantity = entry.get("quantity", 1)
        area_code = entry.get("area_code", "").strip()
        with_area = entry.get("number_with_area_code", "").strip()
        without_area = entry.get("number_without_area_code", "").strip()

        # Determine best pattern
        if with_area:
            search_key = with_area
        else:
            search_key = area_code

        if not search_key or search_key in searched_keys:
            continue  # Skip empty or duplicate

        searched_keys.add(search_key)

        try:
            dummy_number = f"+1{search_key}5551234"
            num = parse(dummy_number, "US")
            region = region_code_for_number(num)
        except NumberParseException:
            print(f"❌ Invalid prefix skipped: {search_key}")
            continue

        print(f"\n🔍 Searching for: {search_key} (limit: {quantity}, region: {region})")

        # -- Plivo Search --
        numbers = ["dummy"]  # Just to pass "non-empty" check
        result = search_plivo_numbers(numbers, search_key, search_key, region, limit=quantity)

        if result:
            results_text += f"\n\n Plivo numbers for {search_key}:\n"
            #print(f"✅ Plivo results for {search_key}:")
            logger.info(f"✅ Plivo results for {search_key}:")
            for r in result:
                results_text += f" - {r['number']}\n"
                print(f" - {r['number']}")
                logger.info(f" - {r['number']}")

            if len(result) >= quantity:
                continue  # No need to fallback
            else:
                print(f"Only {len(result)} out of {quantity} Plivo numbers found - triggering Inteliquent fallback...")
                logger.info(f"Only {len(result)} out of {quantity} Plivo numbers found - triggering Inteliquent fallback...")
        else:
            print(f"❌ No Plivo result. Falling back to Inteliquent for {search_key}...")
            logger.info(f"❌ No Plivo result. Falling back to Inteliquent for {search_key}...")

        # -- Inteliquent Fallback --
        tn_mask = f"{search_key}{'x' * (10 - len(search_key))}"
        iq_payload = {
            "privateKey": iq_private_key,
            "tnMask": tn_mask,
            "quantity" : quantity,
            "reserve": "Y"
        }
        

        try:
            total_results = []
            page = 1
            page_size = 10

            while len(total_results) < quantity:
                iq_payload["pageSort"] = {
                    "property": "state",
                    "direction": "asc",
                    "page": page,
                    "size": min(page_size, quantity - len(total_results))
                }

                iq_response = search_iq_inventory(iq_payload)
                if iq_response.get("statusCode") == "430":
                    try:
                        backorder_response = place_inteliquent_backorder(
                            npa = f"{search_key}",
                            trunk_group=f"{iq_trunk_group}",
                            quantity= f"{quantity}"
                        )
                        order_id = backorder_response.get("orderID")
                        logger.info(f"backorder response:\n{backorder_response}")

                        
                        print(f"Backorder placed successfully for NPA {search_key}. Order ID: {order_id}")
                        logger.info(f"Backorder placed successfully for NPA {search_key}. Order ID: {order_id}")
                        results_text += f"\n\nBackorder placed successfully for NPA {search_key}. Order ID: {order_id}\n"
                    except Exception as e:
                        logger.error(f"Failed to place backorder request for {search_key} : {e}")
                batch = iq_response.get("tnResult", [])
                total_results.extend(batch)

                if not batch or len(batch) < page_size:
                    break  # No more pages
                page += 1

            if total_results:
                print(f"✅ Inteliquent results for {search_key}:")
                results_text += f"\n\nInteliquent results for {search_key}:\n"

                #Print and collect numbers
                tn_list = []
                for tn in total_results[:quantity]:
                    print(f" - {tn['telephoneNumber']} ({tn['city']}, {tn['province']})")
                    results_text += f" - {tn['telephoneNumber']} ({tn['city']}, {tn['province']})\n"

                #Retrieve reserved numbers.
                try:
                    retrieve_payload = {
                        "privatekey" : iq_private_key
                    }
                    retrieve_reserved_iq(payload=retrieve_payload)
                    #Order reserved numbers
                    reserved_data = retrieve_reserved_iq(payload=retrieve_payload)
                    reserved_tns = reserved_data.get("reservedTns", [])
                    print(f"Currently reserved numbers:")
                    results_text += f"\nCurrently reserved numbers:\n"
                    for tn in reserved_tns:
                        print(f": - {tn.get('telephoneNumber')}")
                        results_text += f": - {tn.get('telephoneNumber')}\n"

                    try:
                        order_response = order_reserved_numbers(reserved_tns, iq_private_key, iq_trunk_group)
                        print("Order Response:")
                        print(json.dumps(order_response, indent=5))
                        results_text += f"\n\n{order_response}"
                    except Exception as e:
                        print(f"Failed to order numbers {e}")
                except Exception as e:
                    print(f"Failed to retrieve the reserved numbers: {e}")
                    return e
                
                #Place backorder for remaining quantity
                if len(total_results) < quantity:
                    remaining_quantity = quantity - len(total_results)
                    print(f"Only {len(total_results)} out of {quantity} are found in inteluquent search. Placing backorder request for {remaining_quantity}")
                    logger.info(f"Only {len(total_results)} out of {quantity} are found in inteluquent search. Placing backorder request for {remaining_quantity}")
                    total_results += f"Only {len(total_results)} out of {quantity} are found in inteluquent search. Placing backorder request for {remaining_quantity}"

                    try:
                        backorder_response = place_inteliquent_backorder(
                            npa = f"{search_key}",
                            trunk_group=iq_trunk_group,
                            quantity= f"{remaining_quantity}"
                        )
                        order_id = backorder_response.get('orderId')
                        logger.info(f"backorder response:\n{backorder_response}")
                        print(f"backorder response:\n{backorder_response}")
                        print(f"📦 Backorder placed for {remaining_quantity}. Order ID: {order_id}")
                        logger.info(f"📦 Backorder placed for {remaining_quantity}. Order ID: {order_id}")
                        results_text += f"\n📦 Backorder placed. Order ID: {order_id}\n"
                    except Exception as e:
                        print(f"Failed to place backorder request for {search_key}")
                        logger.info(f"Failed to place backorder request for {search_key}")

            else:
                print(f"❌ No results from Inteliquent for {search_key}")

        except Exception as e:
            print(f"⚠️ Error searching Inteliquent: {e}")
    return full_output + results_text.strip()

# --------------------------- ENTRY POINT ---------------------------

if __name__ == "__main__":
    USER_INPUT = """
I need 1 numbers with area code 235

"""
    handle_user_request(USER_INPUT)
