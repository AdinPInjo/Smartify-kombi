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
    read_individual_temperatures,
    read_relay_states,
    apply_desired_state,
    build_current_state,
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
        
        self.last_gps_fix_file = self.state_dir / "last_gps_fix.json"
        self.applied_version_file = self.state_dir / "applied_version.txt"
        self.last_relay_change_file = self.state_dir / "last_relay_change.json"
    
    def get_last_gps_fix(self) -> Optional[Dict[str, Any]]:
        """
        Get last valid GPS fix
        
        Returns:
            Dictionary with ts (unix timestamp), lat, lon, or None
        """
        try:
            if self.last_gps_fix_file.exists():
                with open(self.last_gps_fix_file, "r") as f:
                    data = json.load(f)
                    # Validate structure
                    if all(k in data for k in ["ts", "lat", "lon"]):
                        return data
        except Exception as e:
            logger.error(f"Error reading last GPS fix: {e}")
        return None
    
    def save_last_gps_fix(self, latitude: float, longitude: float, timestamp: Optional[float] = None):
        """
        Save current GPS fix
        
        Args:
            latitude: GPS latitude
            longitude: GPS longitude
            timestamp: Unix timestamp (defaults to now)
        """
        try:
            data = {
                "ts": timestamp or time.time(),
                "lat": latitude,
                "lon": longitude,
            }
            with open(self.last_gps_fix_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving GPS fix: {e}")
    
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
    
    def get_last_relay_change(self, relay_name: str) -> Optional[float]:
        """
        Get timestamp of last relay state change
        
        Args:
            relay_name: Name of relay (e.g., "heater")
        
        Returns:
            Unix timestamp of last change, or None
        """
        try:
            if self.last_relay_change_file.exists():
                with open(self.last_relay_change_file, "r") as f:
                    data = json.load(f)
                    return data.get(relay_name)
        except Exception as e:
            logger.error(f"Error reading last relay change: {e}")
        return None
    
    def save_relay_change(self, relay_name: str, timestamp: Optional[float] = None):
        """
        Save timestamp of relay state change
        
        Args:
            relay_name: Name of relay (e.g., "heater")
            timestamp: Unix timestamp (defaults to now)
        """
        try:
            data = {}
            if self.last_relay_change_file.exists():
                with open(self.last_relay_change_file, "r") as f:
                    data = json.load(f)
            
            data[relay_name] = timestamp or time.time()
            
            with open(self.last_relay_change_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving relay change: {e}")


# =============================================================================
# Telemetry Loop
# =============================================================================

def calculate_delta_km_safe(
    gps_location: Dict[str, Any],
    last_fix: Optional[Dict[str, Any]],
    current_time: float
) -> Optional[float]:
    """
    Calculate delta_km with safety checks to avoid jitter accumulation
    
    Safety rules:
    - Both fixes must be valid
    - Time delta must be reasonable (<= 10 minutes)
    - Speed sanity check (< 180 km/h)
    - Ignore tiny movements (< 0.03 km) to filter jitter
    
    Args:
        gps_location: Current GPS fix with lat/lon
        last_fix: Last saved fix with ts, lat, lon
        current_time: Current unix timestamp
    
    Returns:
        Distance in km, or None if invalid/filtered
    """
    if not last_fix:
        logger.debug("No previous GPS fix, delta_km = None")
        return None
    
    # Extract coordinates
    lat1 = last_fix.get("lat")
    lon1 = last_fix.get("lon")
    lat2 = gps_location.get("latitude")
    lon2 = gps_location.get("longitude")
    last_ts = last_fix.get("ts")
    
    # Validate all required data
    if None in (lat1, lon1, lat2, lon2, last_ts):
        logger.warning("Incomplete GPS data for delta_km calculation")
        return None
    
    # Check time delta (must be <= 10 minutes)
    time_delta_s = current_time - last_ts
    if time_delta_s > 600:  # 10 minutes
        logger.debug(f"Time delta too large ({time_delta_s:.0f}s), resetting GPS baseline")
        return None
    
    if time_delta_s <= 0:
        logger.warning("Invalid time delta (negative or zero)")
        return None
    
    # Calculate distance
    distance_km = calculate_distance(lat1, lon1, lat2, lon2)
    
    # Filter tiny jitter (< 30 meters = 0.03 km)
    if distance_km < 0.03:
        logger.debug(f"Filtering GPS jitter: {distance_km*1000:.1f}m < 30m threshold")
        return None
    
    # Sanity check: speed must be < 180 km/h
    time_delta_h = time_delta_s / 3600.0
    speed_kmh = distance_km / time_delta_h if time_delta_h > 0 else 999
    
    if speed_kmh > 180:
        logger.warning(f"Unrealistic speed detected: {speed_kmh:.1f} km/h, ignoring delta_km")
        return None
    
    logger.debug(f"Valid delta_km: {distance_km:.3f} km (speed: {speed_kmh:.1f} km/h, time: {time_delta_s:.0f}s)")
    return distance_km


def telemetry_loop(client: RemoteClient, state_manager: StateManager, interval: int = 60):
    """
    Telemetry collection and posting loop
    
    Collects sensor data, calculates delta_km with safety checks,
    posts telemetry, and updates device_state.current_state
    
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
                
                # Calculate delta_km with safety checks (TASK 6)
                delta_km = None
                gps_lat = None
                gps_lon = None
                gps_has_fix = False
                
                if gps_location and gps_location.get('fix'):
                    gps_has_fix = True
                    
                    # Diagnostic: Log full GPS location structure
                    logger.info("GPS fix detected, raw data: %s", gps_location)
                    
                    # Robust extraction: try multiple possible key names
                    # Try: latitude/longitude, lat/lon, gps_lat/gps_lon
                    lat_value = (gps_location.get('latitude') or 
                                gps_location.get('lat') or 
                                gps_location.get('gps_lat'))
                    lon_value = (gps_location.get('longitude') or 
                                gps_location.get('lon') or 
                                gps_location.get('gps_lon'))
                    
                    # Cast to float if string
                    try:
                        if lat_value is not None:
                            gps_lat = float(lat_value)
                        if lon_value is not None:
                            gps_lon = float(lon_value)
                    except (ValueError, TypeError) as e:
                        logger.error("Failed to parse GPS coordinates: lat=%s, lon=%s, error=%s", 
                                   lat_value, lon_value, e)
                        gps_lat = None
                        gps_lon = None
                    
                    # Log parsed values
                    logger.info("GPS parsed: gps_lat=%s, gps_lon=%s, gps_has_fix=%s", 
                              gps_lat, gps_lon, gps_has_fix)
                    
                    # Get last valid GPS fix
                    last_fix = state_manager.get_last_gps_fix()
                    
                    if last_fix:
                        logger.debug(f"Last GPS fix: lat={last_fix.get('lat')}, lon={last_fix.get('lon')}, "
                                   f"age={now - last_fix.get('ts', 0):.0f}s")
                    else:
                        logger.debug("No previous GPS fix found, will establish baseline")
                    
                    # Calculate delta_km with safety checks
                    delta_km = calculate_delta_km_safe(gps_location, last_fix, now)
                    
                    # Save current fix as last fix (even if delta_km was filtered)
                    state_manager.save_last_gps_fix(gps_lat, gps_lon, now)
                    
                    if delta_km is not None:
                        logger.info(f"GPS movement: {delta_km:.3f} km")
                    else:
                        logger.debug("GPS fix available but delta_km filtered (jitter/invalid/first fix)")
                else:
                    logger.debug("No GPS fix available, delta_km = None")
                
                # Safety check: warn if GPS fix reported but coordinates missing
                if gps_has_fix and (gps_lat is None or gps_lon is None):
                    available_keys = list(gps_location.keys()) if gps_location else []
                    logger.warning("GPS fix reported but gps_lat/gps_lon missing - available keys: %s", 
                                 available_keys)
                
                # Post telemetry (TASK 1)
                # Include GPS coordinates in telemetry table when available
                logger.info("Posting telemetry: temp=%s, water=%s, delta_km=%s, gps_lat=%s, gps_lon=%s, gps_fix=%s",
                           temperature_c, water_percent, delta_km, gps_lat, gps_lon, 
                           'yes' if gps_has_fix else 'no')
                
                success = client.post_telemetry(
                    temperature_c=temperature_c,
                    water_percent=water_percent,
                    delta_km=delta_km,
                    gps_lat=gps_lat,  # Send GPS coords to telemetry table
                    gps_lon=gps_lon,  # Send GPS coords to telemetry table
                )
                
                if success:
                    logger.info("Telemetry posted successfully")
                    
                    # Build comprehensive current state snapshot (TASK 2)
                    # This includes GPS coords for admin-only view
                    current_state = build_current_state()
                    
                    # Update device_state.current_state via ackState
                    # Use current applied_version (doesn't increment version, just updates state)
                    applied_version = state_manager.get_applied_version()
                    if client.ack_state(applied_version, current_state):
                        logger.debug("Device state updated")
                        # Log key metrics
                        relays = current_state.get("relays", {})
                        temps = current_state.get("temps", {})
                        gps_state = current_state.get("gps")
                        logger.debug(f"State: relays={relays}, temps={temps}, gps={'fix' if gps_state else 'no fix'}")
                    else:
                        logger.debug("Device state update skipped (expected in local mode)")
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
                        logger.info(f"Desired state: {desired.get('desired_state', {})}")
                        
                        # Apply settings (TASK 4 & 5)
                        desired_state = desired.get("desired_state", {})
                        current_state = apply_desired_state(desired_state, state_manager)
                        
                        # Log what was applied
                        actions = current_state.get("actions_taken", []) or []
                        if actions:
                            logger.info("Applied: %s", '; '.join(str(a) for a in actions))
                        
                        # Check if apply failed (exception) or any critical actions FAILED
                        apply_failed = bool(current_state.get("apply_failed", False))
                        has_failures = any("FAILED" in str(a) for a in actions)
                        
                        if apply_failed or has_failures:
                            logger.error("Apply failed - skipping ACK for version %s", remote_version)
                            if apply_failed:
                                logger.error("Apply error: %s", current_state.get("apply_error"))
                            if has_failures:
                                failed_actions = [a for a in actions if "FAILED" in str(a)]
                                logger.error("Failed actions: %s", failed_actions)
                            # Do NOT ack - will retry next cycle
                            # Do NOT save applied version
                        else:
                            # Acknowledge (TASK 4) - only if no failures
                            if client.ack_state(remote_version, current_state):
                                state_manager.save_applied_version(remote_version)
                                logger.info("Successfully applied and acknowledged version %s", remote_version)
                                
                                # Log relay states after change
                                relays = current_state.get("relays", {})
                                if relays:
                                    logger.info("Relay states after change: %s", relays)
                            else:
                                logger.warning("Failed to acknowledge version %s", remote_version)
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
    logger.info("runner.py path: %s", __file__)
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

