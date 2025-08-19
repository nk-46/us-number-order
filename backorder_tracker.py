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
import logging.handlers
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sqlite3
from dataclasses import dataclass

from mcp_integration import InteliquentOrderTracker, process_completed_order

def setup_logging():
    """Setup optimized logging with rotation"""
    log_dir = "/data" if os.path.exists("/data") else "./data"
    os.makedirs(log_dir, exist_ok=True)
    
    # Create rotating file handler (5MB max, keep 2 files)
    log_file = os.path.join(log_dir, "backorder_tracker.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, 
        maxBytes=5*1024*1024,  # 5MB
        backupCount=2,
        encoding='utf-8'
    )
    
    # Create console handler
    console_handler = logging.StreamHandler()
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Configure logger
    logger = logging.getLogger("backorder_tracker")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Setup logging
logger = setup_logging()

@dataclass
class BackorderRecord:
    """Data class for backorder records"""
    order_id: str
    area_code: str
    quantity: int
    ticket_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    completion_date: Optional[datetime] = None
    last_status: Optional[str] = None  # Track last known status for change detection

class BackorderTracker:
    """Background tracker for Inteliquent backorders"""
    
    def __init__(self, db_path: str = None):
        # Use absolute path by default, fallback to relative for local development
        if db_path is None:
            # Try production path first, fallback to local
            if os.path.exists("/data"):
                db_path = "/data/backorders.db"
            else:
                # Create local data directory if it doesn't exist
                os.makedirs("data", exist_ok=True)
                db_path = "data/backorders.db"
        
        self.db_path = db_path
        self.tracker = InteliquentOrderTracker()
        self.running = False
        self.track_thread = None
        self.last_status_log = 0  # Track when we last logged status
        
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
                    updated_at TEXT,
                    completion_date TEXT
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
            
            current_time = datetime.now().isoformat()
            
            cursor.execute('''
                INSERT OR REPLACE INTO backorders 
                (order_id, area_code, quantity, ticket_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                order_id,
                area_code,
                quantity,
                ticket_id,
                "pending",
                current_time,
                current_time
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"📝 Added backorder {order_id} to tracking")
            
        except Exception as e:
            logger.error(f"❌ Failed to add backorder to tracking: {e}")
    
    def update_backorder_status(self, order_id: str, status: str, completion_date: Optional[datetime] = None):
        """Update backorder status"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            current_time = datetime.now().isoformat()
            completion_date_str = completion_date.isoformat() if completion_date else None
            
            cursor.execute('''
                UPDATE backorders 
                SET status = ?, updated_at = ?, completion_date = ?
                WHERE order_id = ?
            ''', (status, current_time, completion_date_str, order_id))
            
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
                SELECT order_id, area_code, quantity, ticket_id, status, created_at, updated_at, completion_date
                FROM backorders 
                WHERE status = 'pending'
            ''')
            
            records = []
            for row in cursor.fetchall():
                completion_date = datetime.fromisoformat(row[7]) if row[7] else None
                
                record = BackorderRecord(
                    order_id=row[0],
                    area_code=row[1],
                    quantity=row[2],
                    ticket_id=row[3],
                    status=row[4],
                    created_at=datetime.fromisoformat(row[5]),
                    updated_at=datetime.fromisoformat(row[6]),
                    completion_date=completion_date,
                    last_status=None  # Will be set during tracking
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
            note += "Processing numbers for inventory addition...\n"  # Changed: Don't claim MCP integration yet
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
                        datetime.now() # Set completion date to now
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
    
    def remove_completed_backorder(self, order_id: str):
        """Remove a completed backorder from tracking"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM backorders WHERE order_id = ?
            ''', (order_id,))
            
            conn.commit()
            conn.close()
            logger.info(f"📝 Removed completed backorder {order_id} from tracking")
            
        except Exception as e:
            logger.error(f"❌ Failed to remove completed backorder {order_id}: {e}")
    
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
        """Main tracking loop - Optimized for frequent checking with minimal logging"""
        check_count = 0
        last_status_updates = {}  # Track last status update time per backorder
        
        while self.running:
            try:
                check_count += 1
                
                # Get pending backorders
                pending_backorders = self.get_pending_backorders()
                
                if pending_backorders:
                    # Only log summary every 60 checks (10 hours) to reduce log volume
                    if check_count % 60 == 0:
                        logger.info(f"🔍 Monitoring {len(pending_backorders)} pending backorders")
                    
                    for backorder in pending_backorders:
                        # Check ALL backorders regardless of age (frequent monitoring)
                        current_time = datetime.now()
                        
                        # Get status from Inteliquent API (no logging for routine checks)
                        status_result = self.tracker.check_order_status(backorder.order_id)
                        
                        if "error" not in status_result:
                            # Extract order details
                            order_detail = status_result.get("orderDetailResponse", {})
                            current_status = order_detail.get("orderStatus", "unknown")
                            
                            # Check if status has changed
                            status_changed = False
                            if hasattr(backorder, 'last_status') and backorder.last_status != current_status:
                                status_changed = True
                                logger.info(f"🔄 Status change detected for backorder {backorder.order_id}: {backorder.last_status} → {current_status}")
                            
                            # Store current status for next comparison
                            backorder.last_status = current_status
                            
                            # Check if completed
                            if current_status == "Closed":
                                if self.check_backorder_completion(backorder):
                                    logger.info(f"✅ Backorder {backorder.order_id} completed!")
                                    # Remove from tracking after completion
                                    self.remove_completed_backorder(backorder.order_id)
                                else:
                                    logger.warning(f"⚠️ Order {backorder.order_id} is closed but no completed numbers found")
                            
                            # Post status update to Zendesk every 4 hours (regardless of status change)
                            last_update = last_status_updates.get(backorder.order_id)
                            should_update_ticket = (
                                last_update is None or 
                                (current_time - last_update).total_seconds() >= 14400  # 4 hours
                            )
                            
                            if should_update_ticket:
                                self.post_backorder_status_note(backorder, status_result)
                                last_status_updates[backorder.order_id] = current_time
                                logger.info(f"📝 Posted 4-hour status update for backorder {backorder.order_id}")
                            
                            # Log only on status changes (not routine checks)
                            if status_changed:
                                logger.info(f"📊 Backorder {backorder.order_id} status: {current_status}")
                                
                        else:
                            # Only log API errors (important for debugging)
                            logger.warning(f"⚠️ Error checking backorder {backorder.order_id}: {status_result['error']}")
                else:
                    # Only log when no pending backorders every 60 checks (10 hours)
                    if check_count % 60 == 0:
                        logger.info("📋 No pending backorders to monitor")
                
                # Wait 10 minutes before next check (frequent monitoring)
                time.sleep(600)  # 10 minutes
                
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

if __name__ == "__main__":
    """Main entry point for backorder tracker"""
    import signal
    import sys
    
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info("🛑 Received shutdown signal, stopping backorder tracking...")
        stop_backorder_tracking()
        sys.exit(0)
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        logger.info("🚀 Starting backorder tracking service...")
        start_backorder_tracking()
        
        logger.info("✅ Backorder tracking service started successfully")
        logger.info("🔄 Backorder tracking is running. Press Ctrl+C to stop.")
        
        # Keep the main thread alive
        while True:
            time.sleep(60)  # Check every minute
            
    except KeyboardInterrupt:
        logger.info("🛑 Received keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Backorder tracking error: {e}")
        sys.exit(1)
    finally:
        logger.info("🛑 Shutting down backorder tracking...") 