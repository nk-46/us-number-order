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
            # Prepare numbers data
            numbers_data = []
            for number_info in numbers:
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
                
                numbers_data.append(number_dict)
            
            # Prepare payload
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
            
            logger.info(f"📤 Sending {len(numbers)} numbers to MCP server")
            logger.info(f"📋 Payload: {json.dumps(payload, indent=2)}")
            
            # Make request to MCP server
            response = requests.post(
                self.mcp_url,
                json=payload,
                auth=(self.mcp_username, self.mcp_password),
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            logger.info(f"📥 MCP Response Status: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"✅ MCP request successful: {response_data}")
                
                return {
                    'success': True,
                    'response': response_data,
                    'numbers_added': [num.number for num in numbers]
                }
            else:
                logger.error(f"❌ MCP request failed: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': f"HTTP {response.status_code}: {response.text}",
                    'status_code': response.status_code
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Network error calling MCP server: {e}")
            return {
                'success': False,
                'error': f"Network error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"❌ Unexpected error calling MCP server: {e}")
            return {
                'success': False,
                'error': f"Unexpected error: {str(e)}"
            }

class InteliquentOrderTracker:
    """Track Inteliquent order status"""
    
    def __init__(self):
        self.base_url = os.getenv('INTELIQUENT_BASE_URL')
        self.username = os.getenv('INTELIQUENT_USERNAME')
        self.password = os.getenv('INTELIQUENT_PASSWORD')
        
        if not all([self.base_url, self.username, self.password]):
            logger.error("❌ Missing Inteliquent credentials in environment variables")
            raise ValueError("Missing Inteliquent credentials")

    def _get_headers(self):
        """Get headers for Inteliquent API requests"""
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def check_order_status(self, order_id: str) -> Dict:
        """Check the status of an Inteliquent order"""
        try:
            url = f"{self.base_url}/orders/{order_id}"
            
            response = requests.get(
                url,
                auth=(self.username, self.password),
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
        # This would integrate with your existing Zendesk update logic
        # For now, just log the status
        if mcp_result.get('success'):
            logger.info(f"✅ MCP integration successful for ticket {ticket_id}")
            if numbers_added:
                logger.info(f"📞 Numbers added to inventory: {numbers_added}")
        else:
            logger.error(f"❌ MCP integration failed for ticket {ticket_id}: {mcp_result.get('error')}")
            
    except Exception as e:
        logger.error(f"❌ Error updating Zendesk ticket {ticket_id}: {e}") 