#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Integration for Number Inventory
Handles adding numbers to inventory via MCP server with circuit breaker pattern.

ADDITIVE FEATURE:
- Automated number inventory management via MCP
- Circuit breaker for API reliability
- Sequential processing for MCP server limitations
- Region detection for US/Canada numbers
"""

import os
import json
import logging
import requests
import phonenumbers
from phonenumbers import geocoder
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
import base64 # Added for _get_headers

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

def get_region_id_from_area_code(area_code: str) -> int:
    """
    Get region ID based on area code using phonenumbers library
    Returns 101 for US numbers, 102 for Canada numbers
    
    Args:
        area_code: Area code (e.g., "289", "905")
        
    Returns:
        Region ID: 101 for US, 102 for Canada
    """
    try:
        # Create a dummy number with the area code
        dummy_number = f"+1{area_code}5551234"
        
        # Parse the number
        number = phonenumbers.parse(dummy_number, "US")
        
        # Get the region description
        region = geocoder.description_for_number(number, "en")
        
        if region:
            logger.info(f"📋 phonenumbers library found region for area code {area_code}: {region}")
            
            # Check if it's Canada or US based on region description
            if "Canada" in region or region in ["Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba", "Saskatchewan", "Nova Scotia", "New Brunswick", "Newfoundland and Labrador", "Prince Edward Island", "Northwest Territories", "Nunavut", "Yukon"]:
                logger.info(f"🇨🇦 Area code {area_code} belongs to Canada, using region_id 102")
                return 102
            else:
                logger.info(f"🇺🇸 Area code {area_code} belongs to US, using region_id 101")
                return 101
        else:
            logger.warning(f"⚠️ No specific region found for area code {area_code}, defaulting to US (101)")
            return 101
            
    except Exception as e:
        logger.error(f"❌ Error getting region from area code {area_code}: {e}")
        logger.info(f"🇺🇸 Defaulting to US region_id 101 for area code {area_code}")
        return 101

@dataclass
class NumberInfo:
    """Data class for number information"""
    number: str
    number_type: str = "LOCAL"
    voice_enabled: bool = True
    sms_enabled: bool = True
    mms_enabled: bool = True
    carrier_id: str = None
    carrier_tier_id: int = None
    region_id: Optional[int] = None
    city: str = ""
    rate_center: str = ""
    lata: str = ""
    country_iso2: str = "US"
    skip_validation: bool = False
    
    def __post_init__(self):
        if self.carrier_id is None:
            self.carrier_id = os.getenv('MCP_CARRIER_ID')
        if self.carrier_tier_id is None:
            self.carrier_tier_id = int(os.getenv('MCP_CARRIER_TIER_US', '10000252'))

class MCPNumberInventory:
    """MCP client for adding numbers to inventory"""
    
    def __init__(self):
        self.mcp_url = os.getenv('MCP_URL')
        self.mcp_username = os.getenv('MCP_USERNAME')
        self.mcp_password = os.getenv('MCP_PASSWORD')
        
        if not all([self.mcp_url, self.mcp_username, self.mcp_password]):
            logger.error("❌ Missing MCP credentials in environment variables")
            raise ValueError("Missing MCP credentials")

    def add_numbers_to_inventory(self, numbers: List[NumberInfo], user_email: str = "admin@example.com", 
                               skip_number_testing: bool = True, skip_phone_number_profile_restrictions: bool = False,
                               reason_skip_number_testing: str = "Automated addition") -> Dict:
        """
        Add numbers to inventory via MCP server
        
        Args:
            numbers: List of NumberInfo objects
            user_email: Email of the user requesting the addition
            skip_number_testing: Whether to skip number testing
            skip_phone_number_profile_restrictions: Whether to skip phone number profile restrictions
            reason_skip_number_testing: Reason for skipping number testing
            
        Returns:
            Dict with success status and response details
        """
        try:
            # Prepare numbers data with minimal MCP structure
            numbers_data = []
            for number_info in numbers:
                # Ensure number has 1 prefix for MCP (without +)
                number_for_mcp = number_info.number
                if number_for_mcp.startswith("+"):
                    number_for_mcp = number_for_mcp[1:]  # Remove + prefix
                
                # Ensure number starts with 1 (US/Canada country code)
                if not number_for_mcp.startswith("1"):
                    number_for_mcp = "1" + number_for_mcp
                
                number_dict = {
                    "number": number_for_mcp,
                    "number_type": number_info.number_type,
                    "voice_enabled": number_info.voice_enabled,
                    "sms_enabled": number_info.sms_enabled,
                    "mms_enabled": number_info.mms_enabled,
                    "carrier_id": number_info.carrier_id,
                    "carrier_tier_id": number_info.carrier_tier_id
                }
                
                # Only include region_id if it's not None
                if number_info.region_id is not None:
                    number_dict["region_id"] = number_info.region_id
                
                numbers_data.append(number_dict)
            
            # Prepare payload with exact MCP structure
            payload = {
                "query": "add numbers to inventory",
                "raw_args": {
                    "numbers": numbers_data,
                    "user_email": user_email,
                    "skip_number_testing": skip_number_testing,
                    "skip_phone_number_profile_restrictions": skip_phone_number_profile_restrictions,
                    "reason_skip_number_testing": reason_skip_number_testing
                }
            }
            
            print(f"📤 Sending {len(numbers)} numbers to MCP server")
            print(f"📋 MCP Request Payload:")
            print(json.dumps(payload, indent=2))
            
            # Make request to MCP server
            response = requests.post(
                self.mcp_url,
                json=payload,
                auth=(self.mcp_username, self.mcp_password),
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            print(f"📥 MCP Response Status: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                print(f"✅ MCP Response Payload:")
                print(json.dumps(response_data, indent=2))
                
                return {
                    'success': True,
                    'response': response_data,
                    'numbers_added': [num.number for num in numbers]
                }
            else:
                print(f"❌ MCP request failed: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': f"HTTP {response.status_code}: {response.text}",
                    'status_code': response.status_code
                }
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Network error calling MCP server: {e}")
            return {
                'success': False,
                'error': f"Network error: {str(e)}"
            }
        except Exception as e:
            print(f"❌ Unexpected error calling MCP server: {e}")
            return {
                'success': False,
                'error': f"Unexpected error: {str(e)}"
            }

    def block_numbers(self, numbers: List[str], user_email: str = "kiran.a@plivo.com") -> Dict:
        """
        Block numbers using MCP server (one at a time)
        
        Args:
            numbers: List of phone numbers to block
            user_email: Email of the user requesting the block
            
        Returns:
            Dict with success status and response details
        """
        try:
            successful_blocks = []
            failed_blocks = []
            
            print(f"🚫 Processing {len(numbers)} numbers for blocking (one at a time)")
            
            for number in numbers:
                try:
                    # Ensure number has 1 prefix for MCP (without +)
                    number_for_mcp = number
                    if number_for_mcp.startswith("+"):
                        number_for_mcp = number_for_mcp[1:]  # Remove + prefix
                    
                    # Ensure number starts with 1 (US/Canada country code)
                    if not number_for_mcp.startswith("1"):
                        number_for_mcp = "1" + number_for_mcp
                    
                    # Prepare payload for single number blocking (using exact Postman format)
                    payload = json.dumps({
                        "query": "block numbers",
                        "raw_args": {
                            "numbers": [
                                {
                                    "number": number_for_mcp,
                                    "operation": "block"
                                }
                            ],
                            "email_id": user_email
                        }
                    })
                    
                    print(f"🚫 Blocking number: {number_for_mcp}")
                    print(f"📋 MCP Block Request Payload:")
                    print(payload)
                    
                    # Make request to MCP server using exact Postman format
                    headers = {
                        'Content-Type': 'application/json',
                        'Authorization': f'Basic {base64.b64encode(f"{self.mcp_username}:{self.mcp_password}".encode()).decode()}'
                    }
                    
                    response = requests.request(
                        "POST",
                        self.mcp_url,
                        headers=headers,
                        data=payload,
                        timeout=30
                    )
                    
                    print(f"📥 MCP Block Response Status: {response.status_code}")
                    
                    if response.status_code == 200:
                        response_data = response.json()
                        print(f"✅ MCP Block Response Payload:")
                        print(json.dumps(response_data, indent=2))
                        
                        # Check if the response indicates success
                        if response_data.get('status') == 'success':
                            successful_blocks.append(number)
                            print(f"✅ Successfully blocked {number}")
                        else:
                            error_msg = response_data.get('response', {}).get('error', 'Unknown error')
                            failed_blocks.append({
                                'number': number,
                                'error': error_msg
                            })
                            print(f"❌ Failed to block {number}: {error_msg}")
                    else:
                        error_msg = f"HTTP {response.status_code}: {response.text}"
                        failed_blocks.append({
                            'number': number,
                            'error': error_msg
                        })
                        print(f"❌ MCP block request failed for {number}: {error_msg}")
                        
                except Exception as e:
                    error_msg = f"Exception: {str(e)}"
                    failed_blocks.append({
                        'number': number,
                        'error': error_msg
                    })
                    print(f"❌ Error blocking {number}: {error_msg}")
            
            # Return comprehensive result
            return {
                'success': len(successful_blocks) > 0,
                'successful_blocks': successful_blocks,
                'failed_blocks': failed_blocks,
                'total_processed': len(numbers),
                'total_successful': len(successful_blocks),
                'total_failed': len(failed_blocks)
            }
                
        except Exception as e:
            print(f"❌ Unexpected error in block_numbers: {e}")
            return {
                'success': False,
                'error': f"Unexpected error: {str(e)}",
                'successful_blocks': [],
                'failed_blocks': []
            }

class InteliquentOrderTracker:
    """Track Inteliquent order status"""
    
    def __init__(self):
        self.base_url = os.getenv('INTELIQUENT_BASE_URL', 'https://services.inteliquent.com/Services/2.0.0')
        self.private_key = os.getenv('IQ_PRIVATE_KEY')
        self.secret_key = os.getenv('IQ_SECRET_KEY')
        
        if not all([self.base_url, self.private_key, self.secret_key]):
            logger.error("❌ Missing Inteliquent credentials in environment variables")
            raise ValueError("Missing Inteliquent credentials")

    def _get_headers(self):
        """Get headers for Inteliquent API requests"""
        # Encode credentials to Base64 for Basic Auth
        credentials = f"{self.private_key}:{self.secret_key}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Basic {encoded_credentials}'
        }

    def check_order_status(self, order_id: str) -> Dict:
        """Check the status of an Inteliquent order using /orderDetail endpoint"""
        try:
            url = f"{self.base_url}/orderDetail"
            
            # Payload as per Inteliquent API documentation
            payload = {
                "privateKey": self.private_key,
                "orderId": int(order_id)  # orderId must be integer
            }
            
            logger.info(f"🔍 Checking order status for order ID: {order_id}")
            logger.info(f"📤 Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(  # ✅ POST method as per API
                url,
                json=payload,  # ✅ JSON payload
                headers=self._get_headers(),
                timeout=30
            )
            
            logger.info(f"📥 Response Status: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"✅ Order status response: {json.dumps(response_data, indent=2)}")
                return response_data
            else:
                logger.error(f"❌ Failed to check order status: {response.status_code} - {response.text}")
                return {'error': f"HTTP {response.status_code}: {response.text}"}
                
        except Exception as e:
            logger.error(f"❌ Error checking order status: {e}")
            return {'error': str(e)}

    def poll_backorder_status(self, order_id: str) -> Dict:
        """Poll backorder status and return completed numbers"""
        try:
            status_data = self.check_order_status(order_id)
            
            if 'error' in status_data:
                return status_data
            
            # Extract order details from Inteliquent response structure
            order_detail = status_data.get("orderDetailResponse", {})
            order_status = order_detail.get("orderStatus", "")
            
            logger.info(f"📋 Order {order_id} status: {order_status}")
            
            # Check if order is completed (Inteliquent uses "Closed" status)
            if order_status == "Closed":
                # Extract completed numbers from tnList
                completed_numbers = []
                tn_list = order_detail.get("tnList", {}).get("tnItem", [])
                
                for tn_item in tn_list:
                    if tn_item.get("tnStatus") == "Complete":
                        completed_numbers.append(tn_item.get("tn", ""))
                
                logger.info(f"✅ Order {order_id} completed with {len(completed_numbers)} numbers")
                return {
                    'completed': True,
                    'numbers': completed_numbers,
                    'order_id': order_id,
                    'order_status': order_status,
                    'desired_due_date': order_detail.get("desiredDueDate")
                }
            else:
                logger.info(f"⏳ Order {order_id} still in progress: {order_status}")
                return {
                    'completed': False,
                    'status': order_status,
                    'order_id': order_id,
                    'desired_due_date': order_detail.get("desiredDueDate")
                }
                
        except Exception as e:
            logger.error(f"❌ Error polling backorder status: {e}")
            return {'error': str(e)}

def process_completed_order(order_id: str, completed_numbers: List[str], user_email: str = "admin@example.com", ticket_id: str = None) -> Dict:
    """
    Process a completed order by adding numbers to inventory via MCP
    
    Args:
        order_id: Inteliquent order ID
        completed_numbers: List of completed phone numbers
        user_email: Email of the user
        ticket_id: Optional Zendesk ticket ID for logging
        
    Returns:
        Dict with processing results
    """
    try:
        logger.info(f"🔄 Processing completed order {order_id} with {len(completed_numbers)} numbers")
        
        # Create MCP client
        mcp_client = MCPNumberInventory()
        
        # Process each number
        successful_additions = []
        failed_additions = []
        successful_blocks = []
        failed_blocks = []
        
        for number in completed_numbers:
            try:
                # Extract area code from the number
                if number.startswith('+1'):
                    number_without_country = number[2:]  # Remove +1
                elif number.startswith('1'):
                    number_without_country = number[1:]  # Remove 1
                else:
                    number_without_country = number
                
                # Extract area code (first 3 digits)
                area_code = number_without_country[:3]
                
                # Get region ID based on area code
                region_id = get_region_id_from_area_code(area_code)
                
                # Set carrier tier based on region
                carrier_tier_id = int(os.getenv('MCP_CARRIER_TIER_US', '10000252')) if region_id == 101 else int(os.getenv('MCP_CARRIER_TIER_CA', '10000253'))  # US vs Canada
                
                # Create NumberInfo object
                number_info = NumberInfo(
                    number=number,
                    carrier_id=os.getenv('MCP_CARRIER_ID'),
                    carrier_tier_id=carrier_tier_id,
                    region_id=region_id
                )
                
                # Add to inventory
                result = mcp_client.add_numbers_to_inventory(
                    numbers=[number_info],
                    user_email=user_email,
                    skip_number_testing=True,
                    skip_phone_number_profile_restrictions=False,
                    reason_skip_number_testing=f"Completed order {order_id}"
                )
                
                if result.get('success'):
                    successful_additions.append(number)
                    logger.info(f"✅ Successfully added {number} to inventory")
                    
                    # Block the number after successful addition to inventory
                    block_result = mcp_client.block_numbers(
                        numbers=[number],
                        user_email=user_email
                    )
                    
                    if block_result.get('success'):
                        # Add successfully blocked numbers to the list
                        successful_blocks.extend(block_result.get('successful_blocks', []))
                        logger.info(f"🚫 Successfully blocked {number} after inventory addition")
                    else:
                        # Add failed blocks to the list
                        failed_blocks.extend(block_result.get('failed_blocks', []))
                        logger.warning(f"⚠️ Failed to block {number} after inventory addition")
                else:
                    failed_additions.append({
                        'number': number,
                        'error': result.get('error', 'Unknown error')
                    })
                    logger.error(f"❌ Failed to add {number} to inventory: {result.get('error')}")
                    
            except Exception as e:
                failed_additions.append({
                    'number': number,
                    'error': str(e)
                })
                logger.error(f"❌ Error processing number {number}: {e}")
        
        # Prepare result
        result = {
            'order_id': order_id,
            'total_numbers': len(completed_numbers),
            'successful_additions': successful_additions,
            'failed_additions': failed_additions,
            'successful_blocks': successful_blocks,
            'failed_blocks': failed_blocks,
            'ticket_id': ticket_id
        }
        
        logger.info(f"📊 Order processing complete: {len(successful_additions)} successful additions, {len(failed_additions)} failed additions, {len(successful_blocks)} successful blocks, {len(failed_blocks)} failed blocks")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error processing completed order {order_id}: {e}")
        return {
            'error': str(e),
            'order_id': order_id,
            'ticket_id': ticket_id
        }

def update_zendesk_with_mcp_status(ticket_id: str, mcp_result: Dict, numbers_added: List[str] = None):
    """
    Update Zendesk ticket with MCP integration status
    
    Args:
        ticket_id: Zendesk ticket ID
        mcp_result: Result from MCP integration
        numbers_added: List of numbers that were added
    """
    try:
        from zendesk_webhook import post_zendesk_comment
        from datetime import datetime
        
        if mcp_result.get('successful_additions'):
            # ✅ POST SUCCESS NOTE TO ZENDESK
            # Extract additional details from MCP response
            mcp_response = mcp_result.get('response', {})
            inner_response = mcp_response.get('response', {})
            mcp_message = inner_response.get('message', 'Numbers added successfully')
            log_identifier = inner_response.get('log_identifier', 'N/A')
            numbers_processed = inner_response.get('numbers_processed', 0)
            
            internal_comment = f"""
🔄 MCP Integration Complete - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ Numbers Successfully Added to Inventory:
{', '.join(mcp_result['successful_additions'])}

🚫 BLOCKING RESULTS:
✅ Successfully Blocked Numbers:
{', '.join(mcp_result.get('successful_blocks', [])) if mcp_result.get('successful_blocks') else 'None'}

❌ Failed to Block Numbers:
{', '.join([failed['number'] for failed in mcp_result.get('failed_blocks', [])]) if mcp_result.get('failed_blocks') else 'None'}

📊 Summary:
- Total Numbers: {mcp_result['total_numbers']}
- Successful Additions: {len(mcp_result['successful_additions'])}
- Failed Additions: {len(mcp_result.get('failed_additions', []))}
- Numbers Processed: {numbers_processed}
- Successfully Blocked: {len(mcp_result.get('successful_blocks', []))}
- Failed to Block: {len(mcp_result.get('failed_blocks', []))}

🔗 Order ID: {mcp_result['order_id']}
📋 MCP Log ID: {log_identifier}
💬 MCP Message: {mcp_message}
🔄 MCP Status: {mcp_response.get('status', 'N/A')}
⏰ MCP Timestamp: {inner_response.get('timestamp', 'N/A')}
            """
            
            # Add failed numbers details if any
            if mcp_result.get('failed_additions'):
                internal_comment += f"\n❌ Failed Additions:\n"
                for failed in mcp_result['failed_additions']:
                    internal_comment += f"- {failed['number']}: {failed['error']}\n"
            
            # Add failed blocks details if any
            if mcp_result.get('failed_blocks'):
                internal_comment += f"\n⚠️ Failed Blocks:\n"
                for failed in mcp_result['failed_blocks']:
                    internal_comment += f"- {failed['number']}: {failed['error']}\n"
            
            post_zendesk_comment(
                ticket_id=ticket_id,
                internal_comment=internal_comment,
                prefix="mcp_integration"
            )
            logger.info(f"✅ MCP integration success note posted to ticket {ticket_id}")
            
        elif mcp_result.get('error'):
            # ✅ POST ERROR NOTE TO ZENDESK
            internal_comment = f"""
❌ MCP Integration Failed - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🚨 Error: {mcp_result['error']}

🔗 Order ID: {mcp_result.get('order_id', 'N/A')}
            """
            
            post_zendesk_comment(
                ticket_id=ticket_id,
                internal_comment=internal_comment,
                prefix="mcp_integration"
            )
            logger.error(f"❌ MCP integration failure note posted to ticket {ticket_id}")
            
        else:
            # ✅ POST PARTIAL SUCCESS NOTE TO ZENDESK
            internal_comment = f"""
⚠️ MCP Integration Partial Success - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🚫 BLOCKING RESULTS:
✅ Successfully Blocked Numbers:
{', '.join(mcp_result.get('successful_blocks', [])) if mcp_result.get('successful_blocks') else 'None'}

❌ Failed to Block Numbers:
{', '.join([failed['number'] for failed in mcp_result.get('failed_blocks', [])]) if mcp_result.get('failed_blocks') else 'None'}

📊 Summary:
- Total Numbers: {mcp_result.get('total_numbers', 0)}
- Successful Additions: {len(mcp_result.get('successful_additions', []))}
- Failed Additions: {len(mcp_result.get('failed_additions', []))}
- Successfully Blocked: {len(mcp_result.get('successful_blocks', []))}
- Failed to Block: {len(mcp_result.get('failed_blocks', []))}

🔗 Order ID: {mcp_result.get('order_id', 'N/A')}
            """
            
            # Add failed numbers details if any
            if mcp_result.get('failed_additions'):
                internal_comment += f"\n❌ Failed Additions:\n"
                for failed in mcp_result['failed_additions']:
                    internal_comment += f"- {failed['number']}: {failed['error']}\n"
            
            # Add failed blocks details if any
            if mcp_result.get('failed_blocks'):
                internal_comment += f"\n⚠️ Failed Blocks:\n"
                for failed in mcp_result['failed_blocks']:
                    internal_comment += f"- {failed['number']}: {failed['error']}\n"
            
            post_zendesk_comment(
                ticket_id=ticket_id,
                internal_comment=internal_comment,
                prefix="mcp_integration"
            )
            logger.warning(f"⚠️ MCP integration partial success note posted to ticket {ticket_id}")
            
    except Exception as e:
        logger.error(f"❌ Error updating Zendesk ticket {ticket_id}: {e}") 