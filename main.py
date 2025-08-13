#!/usr/bin/env python3
"""
US Number Order System - Main Logic
Handles number search, ordering, and MCP integration for automated inventory management.

ADDITIVE CHANGES:
- MCP integration for automatic number inventory management
- Backorder tracking for Inteliquent orders
- Enhanced error handling and logging
"""

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

# Import MCP integration
from mcp_integration import MCPNumberInventory, NumberInfo, process_completed_order
from backorder_tracker import get_backorder_tracker

# Load environment variables
load_dotenv(override=True)

# --------------------------- SETUP CLIENTS ---------------------------
# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PROJECT_ID = os.getenv("OPENAI_PROJECT_ID")
openai_client = OpenAI(api_key=OPENAI_API_KEY, project=PROJECT_ID)
ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
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
LOG_FILE = "data/us_ca_lc.log"
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


def order_reserved_numbers(reserved_tns, private_key= iq_private_key, trunk_group= iq_trunk_group, endpoint="/tnOrder", method="POST", ticket_id=None):
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
        order_response = response.json()
        
        # Add MCP integration to add numbers to inventory
        try:
            add_numbers_to_inventory_via_mcp(reserved_tns, order_response, ticket_id)
        except Exception as e:
            logger.error(f"⚠️ MCP integration failed: {e}")
        
        return order_response
    else:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")

def add_numbers_to_inventory_via_mcp(reserved_tns, order_response, ticket_id=None):
    """
    Add ordered numbers to inventory via MCP server
    
    Args:
        reserved_tns: List of reserved telephone numbers from Inteliquent
        order_response: Response from Inteliquent order API
        ticket_id: Optional Zendesk ticket ID for status updates
    """
    try:
        # Initialize MCP client
        mcp_client = MCPNumberInventory()
        
        # Convert Inteliquent numbers to NumberInfo objects
        number_infos = []
        numbers_added = []
        for tn in reserved_tns:
            # Extract number from Inteliquent response
            tn_number = tn.get("telephoneNumber") or tn.get("tn")
            if not tn_number:
                continue
                
            # Format number for MCP (ensure + prefix)
            if not tn_number.startswith("+"):
                tn_number = f"+1{tn_number}" if len(tn_number) == 10 else f"+{tn_number}"
            
            numbers_added.append(tn_number)
            
            # Extract additional info from Inteliquent response
            city = tn.get("city", "")
            rate_center = tn.get("rateCenter", "")
            lata = tn.get("lata", "")
            
            # Extract area code for region ID lookup
            area_code = tn_number[2:5] if len(tn_number) >= 5 else ""  # Skip + and country code
            country = "CA" if area_code in ['204', '226', '236', '249', '250', '289', '306', '343', '365', '403', '416', '418', '431', '437', '438', '450', '506', '514', '519', '548', '579', '581', '587', '604', '613', '639', '647', '705', '709', '742', '778', '780', '782', '807', '819', '825', '867', '873', '902', '905'] else "US"
            
            # Determine carrier tier ID based on country using environment variables
            carrier_tier_id = int(os.getenv('MCP_CARRIER_TIER_CA', '10000253')) if country == "CA" else int(os.getenv('MCP_CARRIER_TIER_US', '10000252'))
            
            # Get region_id using simple area code lookup
            from mcp_integration import get_region_id_from_area_code
            region_id = get_region_id_from_area_code(area_code)
            
            number_info = NumberInfo(
                number=tn_number,
                number_type="LOCAL",
                voice_enabled=True,
                sms_enabled=True,
                mms_enabled=True,
                carrier_id=os.getenv('MCP_CARRIER_ID'),  # Use environment variable only
                carrier_tier_id=carrier_tier_id,
                region_id=region_id,  # May be None if not found
                city=city,
                rate_center=rate_center,
                lata=lata,
                country_iso2=country,
                skip_validation=False
            )
            number_infos.append(number_info)
        
        if number_infos:
            # Add numbers to inventory via MCP
            result = mcp_client.add_numbers_to_inventory(
                numbers=number_infos,
                user_email=os.getenv('MCP_USER_EMAIL', 'admin@example.com'),  # Use environment variable
                skip_number_testing=True,
                skip_phone_number_profile_restrictions=False,
                reason_skip_number_testing=f"Automated addition from Inteliquent order {order_response.get('orderId', 'unknown')} - {', '.join([ni.number for ni in number_infos])}"
            )
            
            # Add order ID and structure the result properly for Zendesk status
            order_id = order_response.get('orderId', 'unknown')
            result['order_id'] = order_id
            result['total_numbers'] = len(number_infos)
            
            # Structure the result to match what update_zendesk_with_mcp_status expects
            if result.get("success"):
                # Extract successful numbers from MCP response
                successful_numbers = result.get('numbers_added', [])
                result['successful_additions'] = successful_numbers
                result['failed_additions'] = []
                
                # Log the MCP response details and validate nested response
                mcp_response = result.get('response', {})
                inner_response = mcp_response.get('response', {})
                inner_status = inner_response.get('status', 'unknown')
                mcp_message = inner_response.get('message', 'No message')
                numbers_processed = inner_response.get('numbers_processed', 0)
                log_identifier = inner_response.get('log_identifier', 'N/A')
                
                # Validate the actual MCP response status
                if inner_status == 'success':
                    logger.info(f"✅ Successfully added {len(successful_numbers)} numbers to inventory via MCP")
                    logger.info(f"📋 MCP Message: {mcp_message}")
                    logger.info(f"📋 Numbers Processed: {numbers_processed}")
                    logger.info(f"📋 Log ID: {log_identifier}")
                    logger.info(f"📋 Inner Status: {inner_status}")
                else:
                    logger.warning(f"⚠️ MCP returned success but inner status is: {inner_status}")
                    logger.warning(f"📋 MCP Message: {mcp_message}")
                    # Mark as failed if inner status is not success
                    result['successful_additions'] = []
                    result['failed_additions'] = [{'number': num, 'error': f'MCP inner status: {inner_status}'} for num in numbers_added]
                
                logger.info(f"MCP Result: {json.dumps(result, indent=2)}")
                
                # Update Zendesk ticket with MCP status if ticket_id is provided
                if ticket_id:
                    from mcp_integration import update_zendesk_with_mcp_status
                    update_zendesk_with_mcp_status(
                        ticket_id=ticket_id,
                        mcp_result=result,
                        numbers_added=numbers_added
                    )
            else:
                result['successful_additions'] = []
                result['failed_additions'] = [{'number': num, 'error': result.get('error', 'Unknown error')} for num in numbers_added]
                logger.error(f"❌ Failed to add numbers to inventory via MCP: {result.get('error')}")
                
                # Update Zendesk ticket with MCP failure if ticket_id is provided
                if ticket_id:
                    from mcp_integration import update_zendesk_with_mcp_status
                    update_zendesk_with_mcp_status(
                        ticket_id=ticket_id,
                        mcp_result=result,
                        numbers_added=numbers_added
                    )
        else:
            logger.warning("⚠️ No valid numbers found to add to inventory")
            
    except Exception as e:
        logger.error(f"❌ Exception in MCP integration: {str(e)}")
        raise

def place_inteliquent_backorder(
    npa: str,
    trunk_group: str,
    ticket_id: str,
    activate: str = "Y",
    endpoint: str = request_iq_number_endpoint,
    quantity: int = 1
) -> dict:
    url = f"{iq_api_base_url}{endpoint}"
    payload = {
        "privateKey": iq_private_key,
        "npa": npa,
        "trunkGroup": trunk_group,
        "activate": activate,
        "quantity": quantity
    }

    if ticket_id:
        payload["customerOrderReference"] = f"Ticket_{ticket_id}"

        response = requests.post(url, json=payload, headers=iq_headers)
    
        if response.status_code in [200, 201]:
            logger.info("✅ Backorder placed successfully.")
            logger.info(f"{response.json()}")
            
            backorder_response = response.json()
            order_id = backorder_response.get("orderId") or backorder_response.get("tnOrderId", "N/A")
            
            # Add backorder to tracking
            try:
                tracker = get_backorder_tracker()
                tracker.add_backorder(
                    order_id=order_id,
                    area_code=npa,
                    quantity=quantity,
                    ticket_id=ticket_id
                )
                logger.info(f"📝 Added backorder {order_id} to tracking")
                
                # Post Zendesk note about backorder placement
                if ticket_id:
                    from zendesk_webhook import post_zendesk_comment
                    from datetime import datetime
                    
                    internal_note = f"""
📦 Backorder Placed - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔗 Order ID: {order_id}
📞 Area Code: {npa}
📊 Quantity: {quantity}
⏳ Status: Pending

The backorder has been successfully placed with our carrier. We'll monitor the status and update you when numbers become available.
                    """
                    
                    post_zendesk_comment(
                        ticket_id=ticket_id,
                        internal_comment=internal_note,
                        prefix="backorder_placement"
                    )
                    logger.info(f"📝 Posted backorder placement note to ticket {ticket_id}")
                    
            except Exception as e:
                logger.error(f"⚠️ Failed to add backorder to tracking: {e}")
            
            return backorder_response
        else:
            raise Exception(f"API call failed: {response.status_code} - {response.text}")


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

def run_assistant_with_input(assistant_id, user_message):
    print("📨 Sending user message...")
    thread = openai_client.beta.threads.create()
    openai_client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=user_message
    )

    print("⚙️  Running assistant...")
    run = openai_client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=ASSISTANT_ID
    )

    while True:
        run_status = openai_client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if run_status.status == "completed":
            break
        elif run_status.status in ["failed", "cancelled", "expired"]:
            raise Exception(f"❌ Assistant run failed with status: {run_status.status}")
        time.sleep(1)

    print("📬 Fetching assistant response...")
    messages = openai_client.beta.threads.messages.list(thread_id=thread.id)
    
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


def handle_user_request(user_input,ticket_id=None):
    ai_response = run_assistant_with_input(ASSISTANT_ID, user_input)
    full_output = f"Assitant Response:\n{ai_response}\n\n"
    plivo_summary = {}
    iq_ordered_summary = {}
    iq_backorder_summary = {}
    ordered_number_details = {}

    if not ai_response:
        print("No AI response found.")
        return

    try:
        response_data = json.loads(ai_response)

        # 🚫 Skip if not a number request
        if response_data.get("is_number_request", "").lower() != "yes":
            logger.info("🛑 Skipping processing: is_number_request is not 'Yes'")
            return {
                "skip_update": True,
                "internal": full_output + "\nAssistant indicated this is not a number request.",
                "public": "This request does not appear to be related to number provisioning.",
                "prefix": ""
            }

        # ✅ Filter only Long code type numbers
        numbers_list = [
            entry for entry in response_data.get("numbers", [])
            if entry.get("type", "").lower() == "long code"
        ]
        logger.info(f"📋 Filtered numbers to process: {json.dumps(numbers_list, indent=2)}")

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
            plivo_summary[search_key] = len(result)
            #print(f"✅ Plivo results for {search_key}:")
            logger.info(f"✅ Plivo results for {search_key}:")
            for r in result:
                results_text += f" - {r['number']}\n"
                print(f" - {r['number']}")
                logger.info(f" - {r['number']}")

            # 📝 Post internal note about Plivo numbers found
            if ticket_id:
                try:
                    from zendesk_webhook import post_zendesk_comment
                    from datetime import datetime
                    
                    plivo_numbers = [r['number'] for r in result]
                    internal_note = f"""
📞 Plivo Numbers Found - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔍 Area Code: {search_key}
📊 Quantity Found: {len(result)} (requested: {quantity})
📱 Numbers Available:
{chr(10).join([f"- {num}" for num in plivo_numbers])}

ℹ️ Action Required: Manual rental from Plivo console
- These numbers are available in Plivo inventory
- Please proceed to rent them from your Plivo console
- No MCP integration required for Plivo numbers
- Numbers will be available immediately after rental
                    """
                    
                    post_zendesk_comment(
                        ticket_id=ticket_id,
                        internal_comment=internal_note,
                        prefix="plivo_numbers_found"
                    )
                    logger.info(f"📝 Posted Plivo numbers found note to ticket {ticket_id}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to post Plivo note: {e}")

            if len(result) >= quantity:
                continue  # No need to fallback
            else:
                print(f"Only {len(result)} out of {quantity} Plivo numbers found - triggering Inteliquent fallback...")
                logger.info(f"Only {len(result)} out of {quantity} Plivo numbers found - triggering Inteliquent fallback...")
                
                # 📝 Post note about partial Plivo results and Inteliquent fallback
                if ticket_id:
                    try:
                        from zendesk_webhook import post_zendesk_comment
                        from datetime import datetime
                        
                        remaining_quantity = quantity - len(result)
                        internal_note = f"""
⚠️ Partial Plivo Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔍 Area Code: {search_key}
📊 Plivo Found: {len(result)} (requested: {quantity})
📊 Remaining Needed: {remaining_quantity}

🔄 Action: Proceeding to Inteliquent fallback for remaining quantity
- {len(result)} numbers found in Plivo (manual rental required)
- {remaining_quantity} numbers will be searched in Inteliquent inventory
- If not found, backorder will be placed
                        """
                        
                        post_zendesk_comment(
                            ticket_id=ticket_id,
                            internal_comment=internal_note,
                            prefix="plivo_partial_fallback"
                        )
                        logger.info(f"📝 Posted Plivo partial results note to ticket {ticket_id}")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to post Plivo partial note: {e}")
        else:
            print(f"❌ No Plivo result. Falling back to Inteliquent for {search_key}...")
            logger.info(f"❌ No Plivo result. Falling back to Inteliquent for {search_key}...")
            
            # 📝 Post note about no Plivo results and Inteliquent fallback
            if ticket_id:
                try:
                    from zendesk_webhook import post_zendesk_comment
                    from datetime import datetime
                    
                    internal_note = f"""
❌ No Plivo Numbers Found - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔍 Area Code: {search_key}
📊 Requested: {quantity}

🔄 Action: Proceeding to Inteliquent fallback
- No numbers found in Plivo inventory
- Will search Inteliquent inventory for {quantity} numbers
- If not found, backorder will be placed
                    """
                    
                    post_zendesk_comment(
                        ticket_id=ticket_id,
                        internal_comment=internal_note,
                        prefix="plivo_no_results_fallback"
                    )
                    logger.info(f"📝 Posted no Plivo results note to ticket {ticket_id}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to post no Plivo results note: {e}")

        # -- Inteliquent Fallback --
        tn_mask = f"{search_key}{'x' * (10 - len(search_key))}"
        iq_payload = {
            "privateKey": iq_private_key,
            "tnMask": tn_mask,
            "quantity" : quantity,
            "reserve": "Y"
        }
        backorder_response = None
        try:
            iq_response = search_iq_inventory(iq_payload)

            # === CASE 1: No results at all ===
            if iq_response.get("statusCode") == "430" or not iq_response.get("tnResult"):
                print(f"❌ No inventory in Inteliquent. Placing full backorder for {quantity}")
                logger.info(f"❌ No inventory in Inteliquent. Placing full backorder for {quantity}")
                backorder_response = place_inteliquent_backorder(
                    npa=search_key,
                    trunk_group=iq_trunk_group,
                    ticket_id=ticket_id,
                    quantity=quantity
                    )
                order_id = backorder_response.get("orderId") or backorder_response.get("tnOrderId", "N/A")
                logger.info(f"📦 Full backorder placed. Order ID: {order_id}")
                results_text += f"\n📦 Backorder placed for full quantity. Order ID: {order_id}\n"

                iq_backorder_summary[search_key] = quantity

                continue  # Skip rest of loop

            # === CASE 2: Some results exist ===
            # Modified to use a single request with exact quantity needed
            iq_payload["pageSort"] = {
                "property": "state",
                "direction": "asc",
                "page": 1,
                "size": quantity  # Use the exact quantity needed
            }

            iq_response = search_iq_inventory(iq_payload)
            total_results = iq_response.get("tnResult", [])
            
            if total_results:
                print(f"✅ Inteliquent results for {search_key}:")
                results_text += f"\n\nInteliquent results for {search_key}:\n"

                for tn in total_results:
                    print(f" - {tn['telephoneNumber']} ({tn['city']}, {tn['province']})")
                    results_text += f" - {tn['telephoneNumber']} ({tn['city']}, {tn['province']})\n"

                # Store ordered numbers for this area code
                ordered_number_details[search_key] = [tn.get("telephoneNumber") for tn in total_results]
                print(f"\n Ordered numbers for {search_key}")
                results_text += f"\nOrdered numbers for {search_key}\n"
                for tn in ordered_number_details.get(search_key,[]):
                    print(f": - {tn}\n")
                    results_text += f": - {tn}\n"

                try:
                    order_response = order_reserved_numbers(total_results, iq_private_key, iq_trunk_group, ticket_id=ticket_id)
                    print("Order Response:")
                    iq_ordered_summary[search_key] = len(total_results)
                    logger.info(f"✅ Ordered {len(total_results)} numbers for area code {area_code}")
                    print(json.dumps(order_response, indent=5))
                    results_text += f"\n\n{order_response}"
                    
                    # Note: MCP integration is already handled in order_reserved_numbers function
                    # No need for duplicate MCP integration here
                        
                except Exception as e:
                    print(f"Failed to order numbers {e}")

                # 🔁 Backorder remaining quantity, if needed
                if len(total_results) < quantity:
                    remaining_quantity = quantity - len(total_results)
                    print(f"⚠️ Only {len(total_results)} found. Placing backorder for remaining {remaining_quantity}")
                    backorder_response = place_inteliquent_backorder(
                        npa=search_key,
                        trunk_group=iq_trunk_group,
                        quantity=remaining_quantity,
                        ticket_id=ticket_id
                    )
                    order_id = backorder_response.get("orderId") or backorder_response.get("tnOrderId", "N/A")
                    logger.info(f"📦 Backorder placed for remaining. Order ID: {order_id}")
                    results_text += f"\n📦 Backorder placed for remaining {remaining_quantity}. Order ID: {order_id}\n"
                    logger.info(f"📋 Final Backorder Summary: {json.dumps(iq_backorder_summary, indent=2)}")

                    iq_backorder_summary[search_key] = remaining_quantity


        except Exception as e:
            print(f"⚠️ Error searching Inteliquent: {e}")

    # --------- FORMAT public_text SUMMARY ---------
    public_text = "Hello Team,\n\n"

    if plivo_summary:
        plivo_parts = [f"{ac} {cnt}" for ac, cnt in plivo_summary.items()]
        public_text += (
            "We found numbers via Plivo for the following area codes: "
            + ", ".join(plivo_parts)
            + ". Please proceed to rent them from your console and let us know if you are facing any issues while renting the numbers.\n\n"
        )

    if iq_ordered_summary:
        order_parts = [f"{ac} {cnt}" for ac, cnt in iq_ordered_summary.items()]
        public_text += (
            "We successfully ordered numbers from our carrier for these area codes: "
            + ", ".join(order_parts)
            + ".\n\n"
        )
        for ac, numbers in ordered_number_details.items():
            public_text += f"Here are the numbers provisioned for the area code {ac}: \n"
            for n in numbers:
                public_text += f" - {n}\n"
            public_text += "\n"

    if iq_backorder_summary:
        bo_parts = [f"{ac} {cnt}" for ac, cnt in iq_backorder_summary.items()]
        public_text += (
            "Due to limited inventory, we placed backorder requests for the following area codes: "
            + ", ".join(bo_parts)
            + ". We'll notify you once they're provisioned. Thank you!\n\n"
        )


    print(f"Public text: {public_text}")
    print(f"Prefix: {search_key}")
    print(f"Ordered numbers: {ordered_number_details}")
    internal_comment = full_output + results_text.strip()
    print(f"Internal comment: {internal_comment}")
    print(f"Backorder response: {backorder_response}")
    return {
        "skip_update": False,
        "internal" : full_output + results_text.strip(),
        "public" : public_text,
        "prefix" : str(search_key)
    }

# Note: Removed test code to prevent accidental execution in production