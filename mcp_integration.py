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
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import base64

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging - using logger instead of basicConfig to avoid conflicts
# Main logging configuration is handled in zendesk_webhook.py
logger = logging.getLogger(__name__)

# Circuit breaker for MCP API
class CircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if datetime.now() - self.last_failure_time > timedelta(seconds=self.recovery_timeout):
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            
            raise e

# Initialize circuit breaker for MCP
mcp_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

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
    carrier_id: str = "95201903171584"
    carrier_tier_id: int = 10000252  # US tier
    region_id: Optional[int] = None
    city: str = ""
    rate_center: str = ""
    lata: str = ""
    account_id: int = 12345
    sub_account_id: int = 67890
    app_id: str = "app_123456"
    country_iso2: str = "US"
    skip_validation: bool = False

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
        
        Processes numbers sequentially (one at a time) to avoid MCP server limitations.
        The MCP server has a restriction that only allows one number per request.
        
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
            successful_additions = []
            failed_additions = []
            
            logger.info(f"📤 Processing {len(numbers)} numbers sequentially via MCP")
            
            # Process each number individually to avoid MCP server limitations
            for i, number_info in enumerate(numbers, 1):
                try:
                    logger.info(f"🔄 Processing number {i}/{len(numbers)}: {number_info.number}")
                    
                    # Prepare single number data
                    number_dict = {
                        "number": number_info.number,
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
                    
                    # Prepare payload for single number
                    payload = {
                        "query": "add numbers to inventory",
                        "raw_args": {
                            "numbers": [number_dict],  # Single number in array
                            "user_email": user_email,
                            "skip_number_testing": skip_number_testing,
                            "skip_phone_number_profile_restrictions": skip_phone_number_profile_restrictions,
                            "reason_skip_number_testing": reason_skip_number_testing
                        }
                    }
                    
                    # Make request to MCP server for single number
                    def make_mcp_request():
                        return requests.post(
                            self.mcp_url,
                            json=payload,
                            auth=(self.mcp_username, self.mcp_password),
                            headers={'Content-Type': 'application/json'},
                            timeout=30
                        )
                    
                    # Use circuit breaker for MCP API calls
                    response = mcp_circuit_breaker.call(make_mcp_request)
                    
                    if response.status_code == 200:
                        response_data = response.json()
                        logger.info(f"✅ Successfully added {number_info.number} to inventory")
                        successful_additions.append(number_info.number)
                    else:
                        error_msg = f"HTTP {response.status_code}: {response.text}"
                        logger.error(f"❌ Failed to add {number_info.number}: {error_msg}")
                        failed_additions.append({
                            'number': number_info.number,
                            'error': error_msg
                        })
                        
                except Exception as e:
                    error_msg = f"Exception processing {number_info.number}: {str(e)}"
                    logger.error(f"❌ {error_msg}")
                    failed_additions.append({
                        'number': number_info.number,
                        'error': error_msg
                    })
            
            # Prepare final result
            total_numbers = len(numbers)
            successful_count = len(successful_additions)
            failed_count = len(failed_additions)
            
            logger.info(f"📊 MCP processing complete: {successful_count}/{total_numbers} successful")
            
            if successful_count > 0:
                return {
                    'success': True,
                    'response': {
                        'total_processed': total_numbers,
                        'successful_additions': successful_additions,
                        'failed_additions': failed_additions
                    },
                    'numbers_added': successful_additions
                }
            else:
                return {
                    'success': False,
                    'error': f"All {total_numbers} numbers failed to add",
                    'failed_additions': failed_additions
                }
                
        except Exception as e:
            logger.error(f"❌ Unexpected error in MCP processing: {e}")
            return {
                'success': False,
                'error': f"Unexpected error: {str(e)}"
            }

class InteliquentOrderTracker:
    """Track Inteliquent order status"""
    
    def __init__(self):
        self.base_url = os.getenv('INTELIQUENT_BASE_URL')
        self.username = os.getenv('IQ_PRIVATE_KEY')  # Use existing env var
        self.password = os.getenv('IQ_SECRET_KEY')   # Use existing env var
        
        if not all([self.base_url, self.username, self.password]):
            logger.error("❌ Missing Inteliquent credentials in environment variables")
            raise ValueError("Missing Inteliquent credentials")

    def _get_headers(self):
        """Get headers for Inteliquent API requests with Basic Auth"""
        # Create Basic Auth header with base64-encoded credentials
        credentials = f"{self.username}:{self.password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Basic {encoded_credentials}'
        }

    def check_order_status(self, order_id: str) -> Dict:
        """Check the status of an Inteliquent order"""
        try:
            url = f"{self.base_url}/orderDetail"
            
            # Inteliquent API expects POST with JSON payload
            payload = {
                "privateKey": self.username,
                "orderId": int(order_id) if order_id.isdigit() else order_id
            }
            
            response = requests.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
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
            
            # Check if order is completed
            if status_data.get('status') == 'completed':
                completed_numbers = status_data.get('numbers', [])
                logger.info(f"✅ Order {order_id} completed with {len(completed_numbers)} numbers")
                return {
                    'completed': True,
                    'numbers': completed_numbers,
                    'order_id': order_id
                }
            else:
                logger.info(f"⏳ Order {order_id} still in progress: {status_data.get('status')}")
                return {
                    'completed': False,
                    'status': status_data.get('status'),
                    'order_id': order_id
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
        
        for number in completed_numbers:
            try:
                # Ensure number is in proper format without + prefix
                # Remove any existing + prefix
                if number.startswith('+'):
                    number = number[1:]  # Remove + prefix
                
                # Extract area code from the number (format: 1XXXXXXXXXX)
                if number.startswith('1') and len(number) == 11:
                    number_without_country = number[1:]  # Remove country code 1
                else:
                    number_without_country = number
                
                # Extract area code (first 3 digits)
                area_code = number_without_country[:3]
                
                # Get region ID based on area code
                region_id = get_region_id_from_area_code(area_code)
                
                # Set carrier tier based on region
                carrier_tier_id = 10000252 if region_id == 101 else 10000253  # US vs Canada
                
                # Create NumberInfo object
                number_info = NumberInfo(
                    number=number,
                    carrier_id='95201903171584',
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
            'ticket_id': ticket_id
        }
        
        logger.info(f"📊 Order processing complete: {len(successful_additions)} successful, {len(failed_additions)} failed")
        
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
        # Import Zendesk update function
        from zendesk_webhook import post_zendesk_comment
        
        if mcp_result.get('success'):
            # Success case
            successful_additions = mcp_result.get('response', {}).get('successful_additions', [])
            total_processed = mcp_result.get('response', {}).get('total_processed', 0)
            
            internal_note = f"✅ MCP Integration Success\n\n"
            internal_note += f"Total numbers processed: {total_processed}\n"
            internal_note += f"Successfully added to inventory: {len(successful_additions)}\n"
            
            if successful_additions:
                internal_note += f"Numbers added: {', '.join(successful_additions)}\n"
            
            if numbers_added:
                internal_note += f"Original numbers: {', '.join(numbers_added)}\n"
            
            # Add raw MCP response
            internal_note += f"\n📋 Raw MCP Server Response:\n"
            internal_note += f"{json.dumps(mcp_result, indent=2)}\n"
            
            public_note = f"✅ Successfully added {len(successful_additions)} numbers to inventory via MCP integration."
            
            logger.info(f"✅ MCP integration successful for ticket {ticket_id}")
            logger.info(f"📞 Numbers added to inventory: {successful_additions}")
            
        else:
            # Failure case
            error_msg = mcp_result.get('error', 'Unknown error')
            failed_additions = mcp_result.get('response', {}).get('failed_additions', [])
            
            internal_note = f"❌ MCP Integration Failed\n\n"
            internal_note += f"Error: {error_msg}\n"
            
            if failed_additions:
                internal_note += f"Failed numbers: {len(failed_additions)}\n"
                for failed in failed_additions[:5]:  # Show first 5 failures
                    internal_note += f"- {failed.get('number', 'unknown')}: {failed.get('error', 'unknown error')}\n"
            
            # Add raw MCP response
            internal_note += f"\n📋 Raw MCP Server Response:\n"
            internal_note += f"{json.dumps(mcp_result, indent=2)}\n"
            
            public_note = f"❌ Failed to add numbers to inventory via MCP integration. Error: {error_msg}"
            
            logger.error(f"❌ MCP integration failed for ticket {ticket_id}: {error_msg}")
        
        # Post to Zendesk
        post_zendesk_comment(
            ticket_id=ticket_id,
            internal_comment=internal_note,
            public_comment=public_note
        )
        
        logger.info(f"📝 Posted MCP status to Zendesk ticket {ticket_id}")
            
    except Exception as e:
        logger.error(f"❌ Error updating Zendesk ticket {ticket_id}: {e}") 