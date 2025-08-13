#!/usr/bin/env python3
"""
Backorder Tracking System
Monitors Inteliquent backorders and automatically processes completed orders.

ADDITIVE FEATURE:
- Automated backorder status monitoring
- MCP integration for completed orders
- Status updates to Zendesk tickets
- Age-based filtering (6+ hours)
- Completion date tracking and stop logic
"""

import os
import time
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sqlite3
from dataclasses import dataclass

from mcp_integration import InteliquentOrderTracker, process_completed_order

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class BackorderRecord:
    """Data class for backorder tracking"""
    order_id: str
    ticket_id: Optional[str]
    area_code: str
    quantity: int
    created_at: datetime
    status: str = "pending"
    completed_numbers: List[str] = None
    completion_time: Optional[datetime] = None

class BackorderTracker:
    """Background tracker for Inteliquent backorders"""
    
    def __init__(self, db_path: str = None):
        # Use absolute path by default, fallback to relative for local development
        if db_path is None:
            if os.path.exists("/data"):
                db_path = "/data/backorders.db"
            else:
                db_path = "data/backorders.db"
        
        self.db_path = db_path
        self.tracker = InteliquentOrderTracker()
        self.running = False
        self.track_thread = None
        
        # Initialize database
        self.init_db()
    
    def init_db(self):
        """Initialize the backorder tracking database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS backorders (
                    order_id TEXT PRIMARY KEY,
                    ticket_id TEXT,
                    area_code TEXT,
                    quantity INTEGER,
                    created_at TEXT,
                    status TEXT DEFAULT 'pending',
                    completed_numbers TEXT,
                    completion_time TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ Backorder database initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize backorder database: {e}")
    
    def add_backorder(self, order_id: str, area_code: str, quantity: int, ticket_id: str = None):
        """Add a new backorder to tracking"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO backorders 
                (order_id, ticket_id, area_code, quantity, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                order_id,
                ticket_id,
                area_code,
                quantity,
                datetime.now().isoformat(),
                "pending"
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"📝 Added backorder {order_id} to tracking")
            
        except Exception as e:
            logger.error(f"❌ Failed to add backorder to tracking: {e}")
    
    def update_backorder_status(self, order_id: str, status: str, completed_numbers: List[str] = None):
        """Update backorder status"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            completed_numbers_json = json.dumps(completed_numbers) if completed_numbers else None
            completion_time = datetime.now().isoformat() if status == "completed" else None
            
            cursor.execute('''
                UPDATE backorders 
                SET status = ?, completed_numbers = ?, completion_time = ?
                WHERE order_id = ?
            ''', (status, completed_numbers_json, completion_time, order_id))
            
            conn.commit()
            conn.close()
            
            logger.info(f"📝 Updated backorder {order_id} status to {status}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update backorder status: {e}")
    
    def get_pending_backorders(self) -> List[BackorderRecord]:
        """Get all pending backorders"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT order_id, ticket_id, area_code, quantity, created_at, status, 
                       completed_numbers, completion_time
                FROM backorders 
                WHERE status = 'pending'
            ''')
            
            records = []
            for row in cursor.fetchall():
                completed_numbers = json.loads(row[6]) if row[6] else []
                completion_time = datetime.fromisoformat(row[7]) if row[7] else None
                
                record = BackorderRecord(
                    order_id=row[0],
                    ticket_id=row[1],
                    area_code=row[2],
                    quantity=row[3],
                    created_at=datetime.fromisoformat(row[4]),
                    status=row[5],
                    completed_numbers=completed_numbers,
                    completion_time=completion_time
                )
                records.append(record)
            
            conn.close()
            return records
            
        except Exception as e:
            logger.error(f"❌ Failed to get pending backorders: {e}")
            return []
    
    def create_backorder_status_note(self, backorder: BackorderRecord, status_result: dict) -> str:
        """Create a status note for backorder tracking"""
        
        # Extract order details from Inteliquent response structure
        order_detail = status_result.get("orderDetailResponse", {})
        order_status = order_detail.get("orderStatus", "unknown")
        desired_due_date = order_detail.get("desiredDueDate", "unknown")
        
        # Format the estimated completion date
        try:
            if desired_due_date != "unknown":
                completion_date = datetime.fromisoformat(desired_due_date.replace('Z', '+00:00'))
                formatted_date = completion_date.strftime("%Y-%m-%d %H:%M UTC")
            else:
                formatted_date = "TBD"
        except:
            formatted_date = "TBD"
        
        # Create the status note
        note = f"🔄 Backorder Status Update - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        note += f"Order ID: {backorder.order_id}\n"
        note += f"Area Code: {backorder.area_code}\n"
        note += f"Quantity: {backorder.quantity}\n"
        note += f"Current Status: {order_status.upper()}\n"
        note += f"Estimated Completion: {formatted_date}\n\n"
        
        if order_status == "Closed":
            note += "✅ This backorder has been completed!\n"
            note += "Numbers have been added to inventory via MCP integration.\n"
        elif order_status == "pending":
            note += "📋 This backorder is still being processed by our carrier.\n"
            note += "We'll continue monitoring and update you when numbers become available.\n"
        else:
            note += "⏳ Status is being monitored.\n"
        
        note += f"\nNext status check: {(datetime.now() + timedelta(hours=4)).strftime('%Y-%m-%d %H:%M:%S')}"
        
        return note

    def post_backorder_status_note(self, backorder: BackorderRecord, status_result: dict):
        """Post backorder status note to Zendesk ticket"""
        try:
            from zendesk_webhook import post_zendesk_comment
            
            status_note = self.create_backorder_status_note(backorder, status_result)
            
            post_zendesk_comment(
                ticket_id=backorder.ticket_id,
                internal_comment=status_note,
                public_comment=None  # Status notes are internal only
            )
            
            logger.info(f"📝 Posted status note for backorder {backorder.order_id} to ticket {backorder.ticket_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to post status note: {e}")

    def check_backorder_completion(self, backorder: BackorderRecord) -> bool:
        """Check if a specific backorder is completed"""
        try:
            # Check order status via Inteliquent API
            status_result = self.tracker.check_order_status(backorder.order_id)
            
            if "error" in status_result:
                logger.warning(f"⚠️ Error checking order {backorder.order_id}: {status_result['error']}")
                return False
            
            # Extract order details from Inteliquent response structure
            order_detail = status_result.get("orderDetailResponse", {})
            order_status = order_detail.get("orderStatus", "")
            
            logger.info(f"📋 Order {backorder.order_id} status: {order_status}")
            
            # Check if order is completed (Inteliquent uses "Closed" status)
            if order_status == "Closed":
                # Extract completed numbers from tnList
                completed_numbers = []
                tn_list = order_detail.get("tnList", {}).get("tnItem", [])
                
                for tn_item in tn_list:
                    if tn_item.get("tnStatus") == "Complete":
                        completed_numbers.append(tn_item.get("tn", ""))
                
                if completed_numbers:
                    # Update database
                    self.update_backorder_status(
                        backorder.order_id, 
                        "completed", 
                        completed_numbers
                    )
                    
                    # Process completed numbers via MCP
                    process_result = process_completed_order(
                        order_id=backorder.order_id,
                        completed_numbers=completed_numbers,
                        ticket_id=backorder.ticket_id
                    )
                    
                    # Check if MCP processing was successful (has successful_additions)
                    if process_result.get("successful_additions"):
                        logger.info(f"✅ Successfully processed {len(process_result['successful_additions'])} numbers from backorder {backorder.order_id}")
                        
                        # Update Zendesk ticket with MCP integration status
                        if backorder.ticket_id:
                            from mcp_integration import update_zendesk_with_mcp_status
                            update_zendesk_with_mcp_status(
                                ticket_id=backorder.ticket_id,
                                mcp_result=process_result,
                                numbers_added=process_result['successful_additions']
                            )
                            
                            # Also post the general backorder completion note
                            self.update_zendesk_ticket(
                                ticket_id=backorder.ticket_id,
                                order_id=backorder.order_id,
                                completed_numbers=completed_numbers
                            )
                    elif process_result.get("error"):
                        logger.error(f"❌ Failed to process completed backorder {backorder.order_id}: {process_result.get('error')}")
                        
                        # Post MCP failure note
                        if backorder.ticket_id:
                            from mcp_integration import update_zendesk_with_mcp_status
                            update_zendesk_with_mcp_status(
                                ticket_id=backorder.ticket_id,
                                mcp_result=process_result,
                                numbers_added=[]
                            )
                    else:
                        logger.warning(f"⚠️ No numbers were successfully processed for backorder {backorder.order_id}")
                        
                        # Post partial success note
                        if backorder.ticket_id:
                            from mcp_integration import update_zendesk_with_mcp_status
                            update_zendesk_with_mcp_status(
                                ticket_id=backorder.ticket_id,
                                mcp_result=process_result,
                                numbers_added=[]
                            )
                    
                    return True
                else:
                    logger.warning(f"⚠️ Order {backorder.order_id} is closed but no completed numbers found")
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Exception checking backorder completion: {e}")
            return False
    
    def update_zendesk_ticket(self, ticket_id: str, order_id: str, completed_numbers: List[str]):
        """Update Zendesk ticket with backorder completion"""
        try:
            # Import here to avoid circular imports
            from zendesk_webhook import post_zendesk_comment
            
            message = f"✅ Inteliquent backorder {order_id} completed! {len(completed_numbers)} numbers have been added to inventory."
            internal_note = f"Backorder completion processed. Numbers: {', '.join(completed_numbers)}"
            
            post_zendesk_comment(
                ticket_id=ticket_id,
                internal_comment=internal_note,
                public_comment=message
            )
            
            logger.info(f"📝 Updated Zendesk ticket {ticket_id} with backorder completion")
            
        except Exception as e:
            logger.error(f"❌ Failed to update Zendesk ticket: {e}")
    
    def start_tracking(self):
        """Start background tracking of backorders"""
        if self.running:
            logger.warning("⚠️ Backorder tracking already running")
            return
        
        self.running = True
        self.track_thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.track_thread.start()
        logger.info("🚀 Started backorder tracking")
    
    def stop_tracking(self):
        """Stop background tracking"""
        self.running = False
        if self.track_thread:
            self.track_thread.join()
        logger.info("🛑 Stopped backorder tracking")
    
    def _tracking_loop(self):
        """Main tracking loop"""
        while self.running:
            try:
                # Get pending backorders
                pending_backorders = self.get_pending_backorders()
                
                if pending_backorders:
                    logger.info(f"🔍 Checking {len(pending_backorders)} pending backorders")
                    
                    for backorder in pending_backorders:
                        # Check if backorder is older than 6 hours
                        if datetime.now() - backorder.created_at > timedelta(hours=6):
                            logger.info(f"⏰ Checking backorder {backorder.order_id} (created {backorder.created_at})")
                            
                            # Get status from Inteliquent API
                            status_result = self.tracker.check_order_status(backorder.order_id)
                            
                            if "error" not in status_result:
                                # Post status note every 4 hours
                                self.post_backorder_status_note(backorder, status_result)
                                
                                # Check if completed
                                if status_result.get("status") == "completed":
                                    if self.check_backorder_completion(backorder):
                                        logger.info(f"✅ Backorder {backorder.order_id} completed!")
                                    else:
                                        logger.info(f"⏳ Backorder {backorder.order_id} still pending")
                                else:
                                    logger.info(f"⏳ Backorder {backorder.order_id} still pending")
                            else:
                                logger.warning(f"⚠️ Error checking backorder {backorder.order_id}: {status_result['error']}")
                        else:
                            logger.debug(f"⏰ Backorder {backorder.order_id} too new, skipping")
                
                # Wait 4 hours before next check
                time.sleep(14400)  # 4 hours
                
            except Exception as e:
                logger.error(f"❌ Exception in tracking loop: {e}")
                time.sleep(3600)  # Wait 1 hour on error

# Global tracker instance
backorder_tracker = None

def get_backorder_tracker() -> BackorderTracker:
    """Get or create the global backorder tracker"""
    global backorder_tracker
    if backorder_tracker is None:
        backorder_tracker = BackorderTracker()
    return backorder_tracker

def start_backorder_tracking():
    """Start the backorder tracking service"""
    tracker = get_backorder_tracker()
    tracker.start_tracking()

def stop_backorder_tracking():
    """Stop the backorder tracking service"""
    global backorder_tracker
    if backorder_tracker:
        backorder_tracker.stop_tracking()

# Note: Removed test code to prevent interference with production system 