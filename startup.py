#!/usr/bin/env python3
"""
Startup monitoring service for US Number Order application.
Monitors service health and provides status updates.
"""

import os
import time
import logging
import logging.handlers
import subprocess
import psutil
from datetime import datetime

def setup_logging():
    """Setup optimized logging with rotation"""
    log_dir = "/data" if os.path.exists("/data") else "./data"
    os.makedirs(log_dir, exist_ok=True)
    
    # Create rotating file handler (5MB max, keep 2 files)
    log_file = os.path.join(log_dir, "startup.log")
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
    logger = logging.getLogger("startup_monitor")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def get_system_stats():
    """Get system statistics"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_available_mb': memory.available / (1024 * 1024),
            'disk_percent': disk.percent,
            'disk_free_gb': disk.free / (1024 * 1024 * 1024)
        }
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        return {}

def check_process_health():
    """Check if key processes are running"""
    try:
        # Check for Python processes
        python_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] == 'python3' and proc.info['cmdline']:
                    cmdline = ' '.join(proc.info['cmdline'])
                    if any(script in cmdline for script in ['zendesk_webhook.py', 'backorder_tracker.py', 'startup.py']):
                        python_processes.append({
                            'pid': proc.info['pid'],
                            'script': next((script for script in ['zendesk_webhook.py', 'backorder_tracker.py', 'startup.py'] if script in cmdline), 'unknown')
                        })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return python_processes
    except Exception as e:
        logger.error(f"Error checking process health: {e}")
        return []

def main():
    """Main monitoring loop"""
    logger = setup_logging()
    logger.info("🚀 Startup monitoring service started")
    
    check_count = 0
    last_stats_log = 0
    
    while True:
        try:
            check_count += 1
            
            # Get system stats every 10 checks (20 minutes)
            if check_count % 10 == 0:
                stats = get_system_stats()
                if stats:
                    logger.info(f"📊 System Stats - CPU: {stats['cpu_percent']:.1f}%, "
                              f"Memory: {stats['memory_percent']:.1f}% ({stats['memory_available_mb']:.0f}MB), "
                              f"Disk: {stats['disk_percent']:.1f}% ({stats['disk_free_gb']:.1f}GB free)")
                    last_stats_log = check_count
            
            # Check process health every 5 checks (10 minutes)
            if check_count % 5 == 0:
                processes = check_process_health()
                if processes:
                    process_names = [p['script'] for p in processes]
                    logger.info(f"✅ Process Health - Running: {', '.join(process_names)}")
                else:
                    logger.warning("⚠️ No expected processes found")
            
            # Sleep for 2 minutes between checks
            time.sleep(120)
            
        except KeyboardInterrupt:
            logger.info("🛑 Startup monitoring service stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Error in monitoring loop: {e}")
            time.sleep(60)  # Wait before retrying

if __name__ == "__main__":
    main() 