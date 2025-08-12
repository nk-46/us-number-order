#!/usr/bin/env python3
"""
Startup script for backorder tracking service
Handles graceful startup and shutdown of the backorder tracker
"""

import sys
import os
import signal
import logging
from backorder_tracker import start_backorder_tracking

# Configure logging for startup script
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/data/startup.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("startup")

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"🛑 Received signal {signum}, shutting down gracefully...")
    sys.exit(0)

def main():
    """Main startup function"""
    try:
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("🚀 Starting backorder tracking service...")
        
        # Ensure data directory exists
        os.makedirs("/data", exist_ok=True)
        
        # Start the backorder tracking service
        start_backorder_tracking()
        
    except KeyboardInterrupt:
        logger.info("🛑 Backorder tracking service stopped by user")
    except Exception as e:
        logger.error(f"❌ Backorder tracking service failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 