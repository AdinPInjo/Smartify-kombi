#!/usr/bin/env python3
"""
Remote sync runner - synchronizes telemetry and settings in local or http mode
Runs two independent loops:
- Telemetry loop (60s): collect sensors and post telemetry
- Settings loop (15s): check for new settings and apply them
"""

import os
import sys
import time
import json
import logging
import signal
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from remote_sync.remote_client import RemoteClient
from remote_sync.adapters import (
    read_temperature,
    read_water_level,
    read_gps_location,
    apply_desired_state,
)

# Configure logging
LOG_FILE = "/var/log/smartify/remote_sync.log"
LOG_DIR = Path(LOG_FILE).parent
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_flag = False


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global shutdown_flag
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_flag = True


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# =============================================================================
# GPS and State Management
# =============================================================================

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two GPS coordinates in kilometers using Haversine formula
    
    Args:
        lat1, lon1: First coordinate
        lat2, lon2: Second coordinate
    
    Returns:
        Distance in kilometers
    """
    R = 6371  # Earth's radius in kilometers
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    
    return R * c


class StateManager:
    """Manages persistent local state"""
    
    def __init__(self):
        self.state_dir = Path("/var/lib/smartify")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.last_gps_file = self.state_dir / "last_gps.json"
        self.applied_version_file = self.state_dir / "applied_version.txt"
    
    def get_last_gps(self) -> Optional[Dict[str, float]]:
        """Get last GPS position"""
        try:
            if self.last_gps_file.exists():
                with open(self.last_gps_file, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error reading last GPS: {e}")
        return None
    
    def save_last_gps(self, latitude: float, longitude: float):
        """Save current GPS position"""
        try:
            data = {
                "latitude": latitude,
                "longitude": longitude,
                "timestamp": datetime.now().isoformat()
            }
            with open(self.last_gps_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving GPS: {e}")
    
    def get_applied_version(self) -> int:
        """Get last applied settings version"""
        try:
            if self.applied_version_file.exists():
                with open(self.applied_version_file, "r") as f:
                    return int(f.read().strip())
        except Exception as e:
            logger.error(f"Error reading applied version: {e}")
        return 0
    
    def save_applied_version(self, version: int):
        """Save applied settings version"""
        try:
            with open(self.applied_version_file, "w") as f:
                f.write(str(version))
        except Exception as e:
            logger.error(f"Error saving applied version: {e}")


# =============================================================================
# Telemetry Loop
# =============================================================================

def telemetry_loop(client: RemoteClient, state_manager: StateManager, interval: int = 60):
    """
    Telemetry collection and posting loop
    
    Args:
        client: RemoteClient instance
        state_manager: StateManager instance
        interval: Loop interval in seconds
    """
    logger.info(f"Starting telemetry loop (interval={interval}s)")
    last_run = 0
    
    while not shutdown_flag:
        try:
            now = time.time()
            
            if now - last_run >= interval:
                # Read sensors
                temperature_c = read_temperature()
                water_percent = read_water_level()
                gps_location = read_gps_location()
                
                # Calculate delta_km if GPS available
                delta_km = None
                gps_lat = None
                gps_lon = None
                
                if gps_location:
                    gps_lat = gps_location['latitude']
                    gps_lon = gps_location['longitude']
                    
                    last_gps = state_manager.get_last_gps()
                    if last_gps:
                        delta_km = calculate_distance(
                            last_gps['latitude'],
                            last_gps['longitude'],
                            gps_lat,
                            gps_lon
                        )
                        logger.debug(f"Calculated delta_km: {delta_km:.3f} km")
                    
                    # Save current GPS as last position
                    state_manager.save_last_gps(gps_lat, gps_lon)
                
                # Post telemetry
                logger.info(f"Posting telemetry: temp={temperature_c}, water={water_percent}, "
                           f"delta_km={delta_km}, gps={'yes' if gps_location else 'no'}")
                
                success = client.post_telemetry(
                    temperature_c=temperature_c,
                    water_percent=water_percent,
                    delta_km=delta_km,
                    gps_lat=gps_lat,
                    gps_lon=gps_lon,
                )
                
                if success:
                    logger.info("Telemetry posted successfully")
                else:
                    logger.warning("Failed to post telemetry")
                
                last_run = now
            
            # Sleep briefly to avoid busy loop
            time.sleep(1)
        
        except Exception as e:
            logger.error(f"Error in telemetry loop: {e}", exc_info=True)
            time.sleep(5)  # Wait before retrying


# =============================================================================
# Settings Loop
# =============================================================================

def settings_loop(client: RemoteClient, state_manager: StateManager, interval: int = 15):
    """
    Settings check and apply loop
    
    Args:
        client: RemoteClient instance
        state_manager: StateManager instance
        interval: Loop interval in seconds
    """
    logger.info(f"Starting settings loop (interval={interval}s)")
    last_run = 0
    
    while not shutdown_flag:
        try:
            now = time.time()
            
            if now - last_run >= interval:
                # Get desired state
                desired = client.get_desired_state()
                
                if desired:
                    remote_version = desired.get("version", 0)
                    local_version = state_manager.get_applied_version()
                    
                    logger.debug(f"Version check: remote={remote_version}, local={local_version}")
                    
                    if remote_version > local_version:
                        logger.info(f"New settings version {remote_version} detected, applying...")
                        
                        # Apply settings
                        desired_state = desired.get("desired_state", {})
                        current_state = apply_desired_state(desired_state)
                        
                        # Acknowledge
                        if client.ack_state(remote_version, current_state):
                            state_manager.save_applied_version(remote_version)
                            logger.info(f"Successfully applied and acknowledged version {remote_version}")
                        else:
                            logger.warning(f"Failed to acknowledge version {remote_version}")
                    else:
                        logger.debug("Settings up to date")
                else:
                    logger.debug("No desired state available")
                
                last_run = now
            
            # Sleep briefly to avoid busy loop
            time.sleep(1)
        
        except Exception as e:
            logger.error(f"Error in settings loop: {e}", exc_info=True)
            time.sleep(5)  # Wait before retrying


# =============================================================================
# Main
# =============================================================================

def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("Smartify Remote Sync starting...")
    logger.info("=" * 60)
    
    try:
        # Initialize components
        mode = os.getenv("SMARTIFY_REMOTE_MODE", "local")
        logger.info(f"Mode: {mode}")
        
        client = RemoteClient(mode=mode)
        state_manager = StateManager()
        
        logger.info("All components initialized successfully")
        
        # Run loops in separate threads
        telemetry_thread = threading.Thread(
            target=telemetry_loop,
            args=(client, state_manager, 60),
            daemon=True,
            name="TelemetryLoop"
        )
        
        settings_thread = threading.Thread(
            target=settings_loop,
            args=(client, state_manager, 15),
            daemon=True,
            name="SettingsLoop"
        )
        
        telemetry_thread.start()
        settings_thread.start()
        
        logger.info("All loops started, running...")
        
        # Main thread waits for shutdown
        while not shutdown_flag:
            time.sleep(1)
        
        logger.info("Shutdown initiated, waiting for threads...")
        telemetry_thread.join(timeout=5)
        settings_thread.join(timeout=5)
        
        logger.info("Shutdown complete")
    
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

