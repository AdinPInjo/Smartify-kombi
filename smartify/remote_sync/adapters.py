"""
Adapters for sensor reading and control functions.
This module provides a clean interface to existing smartify code.

Supports two methods:
1. Direct imports from smartify modules (preferred)
2. HTTP API fallback (if imports fail or modules are not available)
"""

import os
import time as pytime
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# HTTP API configuration
LOCAL_API_BASE = os.getenv("SMARTIFY_LOCAL_API_BASE", "http://127.0.0.1:8000")
API_TIMEOUT = 5  # seconds


# =============================================================================
# Sensor Reading Adapters
# =============================================================================

def read_temperature() -> Optional[float]:
    """
    Read current temperature in Celsius
    
    Tries:
    1. Direct import from temp_logger module
    2. HTTP API fallback to /api/temperature/latest
    
    Returns:
        Temperature in Celsius (average of all sensors), or None if unavailable
    """
    # Try direct import first
    try:
        from smartify.temp_logger import read_temperature as _read_temp
        temp = _read_temp()
        if temp is not None:
            logger.debug(f"Temperature from direct import: {temp}°C")
            return temp
    except ImportError:
        logger.debug("temp_logger not available, trying HTTP API")
    except Exception as e:
        logger.warning(f"Error reading temperature via import: {e}")
    
    # Fallback to HTTP API
    try:
        url = f"{LOCAL_API_BASE}/api/temperature/latest"
        response = requests.get(url, timeout=API_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            sensors = data.get("sensors", [])
            
            # Calculate average temperature from all sensors
            temps = []
            for sensor in sensors:
                temp_c = sensor.get("temperature_c") or sensor.get("temp_c")
                if temp_c is not None:
                    temps.append(float(temp_c))
            
            if temps:
                avg_temp = sum(temps) / len(temps)
                logger.debug(f"Temperature from HTTP API: {avg_temp}°C (avg of {len(temps)} sensors)")
                return avg_temp
            else:
                logger.warning("HTTP API returned no valid temperature readings")
                return None
        else:
            logger.warning(f"HTTP API returned status {response.status_code}")
            return None
    
    except requests.exceptions.RequestException as e:
        logger.warning(f"HTTP API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading temperature via HTTP API: {e}")
        return None


def read_individual_temperatures() -> Dict[str, Optional[float]]:
    """
    Read individual temperature sensors
    
    Returns:
        Dictionary with t1, t2, avg keys, or empty dict if unavailable
    """
    try:
        url = f"{LOCAL_API_BASE}/api/temperature/latest"
        response = requests.get(url, timeout=API_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            sensors = data.get("sensors", [])
            
            result = {"t1": None, "t2": None, "avg": None}
            temps = []
            
            for sensor in sensors:
                temp_c = sensor.get("temperature_c")
                sensor_idx = sensor.get("sensor_index", 0)
                
                if temp_c is not None:
                    temps.append(float(temp_c))
                    if sensor_idx == 0:
                        result["t1"] = float(temp_c)
                    elif sensor_idx == 1:
                        result["t2"] = float(temp_c)
            
            if temps:
                result["avg"] = sum(temps) / len(temps)
            
            logger.debug(f"Individual temps: t1={result['t1']}, t2={result['t2']}, avg={result['avg']}")
            return result
        
    except Exception as e:
        logger.warning(f"Error reading individual temperatures: {e}")
    
    return {"t1": None, "t2": None, "avg": None}


def read_water_level() -> Optional[float]:
    """
    Read current water level as percentage (0-100)
    
    Tries:
    1. Direct import from water_level.reader module
    2. HTTP API fallback to /api/water/level/live
    
    Returns:
        Water level percentage, or None if unavailable
    """
    # Try direct import first
    try:
        from smartify.water_level.reader import WaterLevelReader
        reader = WaterLevelReader()
        reading = reader.read()
        if reading and hasattr(reading, 'percent'):
            percent = reading.percent
            if percent is not None:
                logger.debug(f"Water level from direct import: {percent}%")
                return float(percent)
    except ImportError:
        logger.debug("WaterLevelReader not available, trying HTTP API")
    except Exception as e:
        logger.warning(f"Error reading water level via import: {e}")
    
    # Fallback to HTTP API
    try:
        url = f"{LOCAL_API_BASE}/api/water/level/live"
        response = requests.get(url, timeout=API_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            
            # Try multiple possible keys for water level percentage
            percent = None
            for key in ["level_percent", "water_percent", "percent", "percentage"]:
                if key in data and data[key] is not None:
                    percent = data[key]
                    break
            
            if percent is not None:
                logger.debug(f"Water level from HTTP API: {percent}%")
                return float(percent)
            else:
                logger.warning(f"HTTP API returned no valid water level (ok={data.get('ok')}, status={data.get('status')})")
                return None
        else:
            logger.warning(f"HTTP API returned status {response.status_code}")
            return None
    
    except requests.exceptions.RequestException as e:
        logger.warning(f"HTTP API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading water level via HTTP API: {e}")
        return None


def read_gps_location() -> Optional[Dict[str, Any]]:
    """
    Read current GPS location with detailed fix information
    
    Tries:
    1. HTTP API fallback to /api/gps/current
    
    Returns:
        Dictionary with GPS data including fix quality, or None if no fix
        Structure: {
            'latitude': float,
            'longitude': float,
            'fix': bool,
            'sats': int (optional),
            'hdop': float (optional),
            'speed_kmh': float (optional),
            'altitude_m': float (optional)
        }
    """
    try:
        url = f"{LOCAL_API_BASE}/api/gps/current"
        response = requests.get(url, timeout=API_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check if GPS data is valid
            if data.get("ok") is False:
                logger.debug("GPS API: No fix available")
                return None
            
            lat = data.get("lat")
            lon = data.get("lon")
            
            # Validate coordinates
            if lat is None or lon is None:
                logger.debug("GPS API: Coordinates not available")
                return None
            
            # Validate coordinate ranges
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                logger.warning(f"GPS API: Invalid coordinates: lat={lat}, lon={lon}")
                return None
            
            # Build GPS data object
            gps_data = {
                'latitude': float(lat),
                'longitude': float(lon),
                'fix': True,  # We only return data if fix is valid
            }
            
            # Add optional metadata
            if 'speed_kmh' in data and data['speed_kmh'] is not None:
                gps_data['speed_kmh'] = float(data['speed_kmh'])
            
            # Note: API may not provide sats/hdop, but we include them if available
            # These would need to be added to the GPS API endpoint
            
            logger.debug(f"GPS fix: lat={lat:.6f}, lon={lon:.6f}, speed={gps_data.get('speed_kmh', 'N/A')} km/h")
            return gps_data
        else:
            logger.warning(f"GPS API returned status {response.status_code}")
            return None
    
    except requests.exceptions.RequestException as e:
        logger.warning(f"GPS API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading GPS: {e}")
        return None


# =============================================================================
# Relay State Reading
# =============================================================================

def read_relay_states() -> Dict[str, Any]:
    """
    Read current state of all relays
    
    Returns:
        Dictionary with relay names as keys and their states
        Example: {"heater": {"state": "on", "mode": "auto"}}
    """
    try:
        url = f"{LOCAL_API_BASE}/api/relays"
        response = requests.get(url, timeout=API_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            relays_list = data.get("relays", [])
            
            result = {}
            for relay in relays_list:
                name = relay.get("name")
                if name:
                    result[name] = {
                        "state": relay.get("state", "unknown"),
                        "mode": relay.get("mode", "unknown"),
                        "is_enabled": relay.get("is_enabled", False),
                    }
            
            logger.debug(f"Read relay states: {list(result.keys())}")
            return result
        else:
            logger.warning(f"Failed to read relay states: status={response.status_code}")
            return {}
    
    except Exception as e:
        logger.warning(f"Error reading relay states: {e}")
        return {}


# =============================================================================
# Control Function Adapters
# =============================================================================

def set_relay_state(relay_name: str, state: str, mode: str = "manual", duration_minutes: Optional[int] = None) -> bool:
    """
    Set relay state via HTTP API
    
    Args:
        relay_name: Name of relay (e.g. "heater", "pump", "lights")
        state: "on" or "off"
        mode: "manual" or "auto"
        duration_minutes: Optional duration for manual mode
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # First get relay ID by name
        url = f"{LOCAL_API_BASE}/api/relays"
        response = requests.get(url, timeout=API_TIMEOUT)
        
        if response.status_code != 200:
            logger.error(f"Failed to get relays list: status={response.status_code}")
            return False
        
        relays = response.json().get("relays", [])
        relay = next((r for r in relays if r.get("name") == relay_name), None)
        
        if not relay:
            logger.error(f"Relay '{relay_name}' not found")
            return False
        
        relay_id = relay.get("id")
        
        # Set relay state
        url = f"{LOCAL_API_BASE}/api/relays/{relay_id}/state"
        payload = {
            "state": state,
            "mode": mode,
        }
        
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        
        response = requests.post(url, json=payload, timeout=API_TIMEOUT)
        
        if response.status_code == 200:
            logger.info(f"Set relay '{relay_name}' to {state} ({mode} mode)")
            return True
        else:
            logger.warning(f"Failed to set relay '{relay_name}': status={response.status_code}, response={response.text[:200]}")
            return False
    
    except Exception as e:
        logger.error(f"Error setting relay '{relay_name}': {e}")
        return False


def apply_heater_setting(enabled: bool, verify: bool = True) -> bool:
    """
    Enable or disable heater with state verification
    
    Args:
        enabled: True to enable, False to disable
        verify: If True, verify state change by re-reading relay states
    
    Returns:
        True if successful and verified, False otherwise
    """
    state = "on" if enabled else "off"
    
    # Apply the setting
    if not set_relay_state("heater", state, mode="manual"):
        logger.error(f"Failed to set heater to {state}")
        return False
    
    if not verify:
        return True
    
    # Verify the state change (retry up to 5 times)
    import time
    for attempt in range(5):
        time.sleep(0.2)  # Wait for relay to switch
        relays = read_relay_states()
        if relays:
            heater_state = relays.get("heater", {}).get("state", "unknown")
            if heater_state == state:
                logger.debug(f"Heater state verified: {state}")
                return True
            logger.debug(f"Heater state check attempt {attempt + 1}: expected={state}, actual={heater_state}")
    
    logger.error(f"Failed to verify heater state change to {state} after 5 attempts")
    return False


def apply_pump_setting(enabled: bool, verify: bool = True) -> bool:
    """
    Enable or disable water pump with state verification
    
    Args:
        enabled: True to enable, False to disable
        verify: If True, verify state change by re-reading relay states
    
    Returns:
        True if successful and verified, False otherwise
    """
    state = "on" if enabled else "off"
    
    # Apply the setting
    if not set_relay_state("pump", state, mode="manual"):
        logger.error(f"Failed to set pump to {state}")
        return False
    
    if not verify:
        return True
    
    # Verify the state change (retry up to 5 times)
    for attempt in range(5):
        pytime.sleep(0.2)  # Wait for relay to switch
        relays = read_relay_states()
        if relays:
            pump_state = relays.get("pump", {}).get("state", "unknown")
            if pump_state == state:
                logger.debug(f"Pump state verified: {state}")
                return True
            logger.debug(f"Pump state check attempt {attempt + 1}: expected={state}, actual={pump_state}")
    
    logger.error(f"Failed to verify pump state change to {state} after 5 attempts")
    return False


def apply_lighting_mode(mode: str) -> bool:
    """
    Set lighting mode
    
    Args:
        mode: "off", "dim", or "on"
    
    Returns:
        True if successful, False otherwise
    """
    # Map lighting modes to relay states
    if mode == "off":
        return set_relay_state("lights", "off", mode="manual")
    elif mode in ("dim", "on"):
        # For now, treat both dim and on as "on"
        # Could be enhanced with PWM control later
        return set_relay_state("lights", "on", mode="manual")
    else:
        logger.warning(f"Unknown lighting mode: {mode}")
        return False


def apply_target_temperature(temp_c: float) -> bool:
    """
    Set target temperature (placeholder for future heater control logic)
    
    Args:
        temp_c: Target temperature in Celsius
    
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Target temperature set to {temp_c}°C (stored for heater automation)")
        # This could be stored in a local file for heater rules to use
        return True
    except Exception as e:
        logger.error(f"Error setting target temperature: {e}")
        return False


# =============================================================================
# Settings Application
# =============================================================================

def get_system_uptime() -> Optional[int]:
    """Get system uptime in seconds"""
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.read().split()[0])
            return int(uptime_seconds)
    except Exception as e:
        logger.warning(f"Error reading uptime: {e}")
        return None


def build_current_state() -> Dict[str, Any]:
    """
    Build comprehensive current state snapshot for device_state.current_state
    
    Structure matches admin-only view requirements:
    - gps: null if no fix, otherwise {lat, lon, fix, sats, hdop, speed_kmh}
    - temps: {t1, t2, avg}
    - relays: {heater: "on"/"off", pump: "on"/"off", ...}
    - water_percent: float
    - uptime_s: int
    
    Returns:
        Dictionary with complete device state
    """
    current_state = {}
    
    try:
        # Read GPS (null if no fix, admin-only - never exposed publicly)
        gps = read_gps_location()
        if gps:
            # Include detailed GPS metadata for admin
            current_state["gps"] = {
                "lat": gps.get("latitude"),
                "lon": gps.get("longitude"),
                "fix": gps.get("fix", True),
            }
            # Add optional metadata if available
            if "speed_kmh" in gps:
                current_state["gps"]["speed_kmh"] = gps["speed_kmh"]
            if "sats" in gps:
                current_state["gps"]["sats"] = gps["sats"]
            if "hdop" in gps:
                current_state["gps"]["hdop"] = gps["hdop"]
        else:
            current_state["gps"] = None
        
        # Read individual temperatures
        temps = read_individual_temperatures()
        if temps and any(v is not None for v in temps.values()):
            current_state["temps"] = temps
        else:
            current_state["temps"] = {"t1": None, "t2": None, "avg": None}
        
        # Read relay states
        relays = read_relay_states()
        if relays:
            current_state["relays"] = {
                name: data["state"] for name, data in relays.items()
            }
        else:
            current_state["relays"] = {}
        
        # Read water level
        water = read_water_level()
        current_state["water_percent"] = water  # Can be None
        
        # Read uptime
        uptime = get_system_uptime()
        current_state["uptime_s"] = uptime  # Can be None
        
    except Exception as e:
        logger.error(f"Error building current state: {e}")
        current_state["error"] = str(e)
    
    return current_state


def normalize_relay_value(value: Any) -> Optional[str]:
    """
    Normalize relay value to "on" or "off"
    
    Accepts: "on"/"off" (case-insensitive), True/False, 1/0
    
    Returns:
        "on", "off", or None if invalid
    """
    if isinstance(value, str):
        value_lower = value.lower().strip()
        if value_lower in ("on", "true", "1"):
            return "on"
        elif value_lower in ("off", "false", "0"):
            return "off"
    elif isinstance(value, bool):
        return "on" if value else "off"
    elif isinstance(value, (int, float)):
        return "on" if value else "off"
    
    return None


def apply_desired_state(desired_state: Dict[str, Any], state_manager: Any = None) -> Dict[str, Any]:
    """
    Apply desired state to device with heater automation rules (TASK 4 & 5)
    
    Supported desired_state schemas (backward/forward compatible):
    
    Schema 1 - Direct relay control (MANUAL override, highest priority):
    - relays: {"heater": "on"|"off", "pump": "on"|"off"}
      → Treated as MANUAL override (heater_force="on"/"off", heater_auto=false)
      → Applies IMMEDIATELY (no hold-time)
    
    Schema 2 - Automation control:
    - heater_auto: bool (enable automatic heater control)
    - heater_on_below_c: float (turn heater on below this temp)
    - heater_off_above_c: float (turn heater off above this temp)
    - heater_force: "on" | "off" | "auto" (override auto mode)
    - pump_force: "on" | "off"
    - lights_mode: "off" | "dim" | "on"
    
    Priority:
    1. relays.heater (MANUAL override) - applies immediately, no hold-time
    2. heater_force "on"/"off" - applies immediately, no hold-time
    3. heater_auto + thresholds - applies with hold-time (prevents oscillation)
    
    Heater automation rules (TASK 5):
    - Force modes override auto
    - Auto mode uses temperature thresholds with hysteresis
    - Minimum hold time (5 minutes) prevents oscillation for AUTO decisions only
    - Invalid config (on_below >= off_above) is ignored
    
    Args:
        desired_state: Dictionary with settings
        state_manager: Optional StateManager for tracking relay changes
    
    Returns:
        Dictionary with actual current state after applying
    """
    # Proof: Log which file is running
    logger.info("apply_desired_state() using adapters.py: %s", __file__)
    logger.debug("pytime available: %s", "yes" if pytime else "no")
    logger.info("Applying desired state: %s", desired_state)
    
    actions_taken = []
    apply_failed = False  # Track if apply failed with exception
    apply_error = None  # Store error message
    MIN_HOLD_TIME_S = 300  # 5 minutes minimum between heater changes (AUTO mode only)
    
    # =========================================================================
    # STEP 1: Normalize relays schema to standard fields
    # =========================================================================
    relays_cmd = desired_state.get("relays", {})
    if isinstance(relays_cmd, dict) and relays_cmd:
        logger.info(f"Detected relays override: {relays_cmd}")
        
        # Map relays.heater to heater_force (MANUAL override)
        if "heater" in relays_cmd:
            heater_value = normalize_relay_value(relays_cmd["heater"])
            if heater_value:
                desired_state["heater_force"] = heater_value
                desired_state["heater_auto"] = False  # Disable auto when manual override
                logger.info(f"Mapped relays.heater={relays_cmd['heater']} -> heater_force={heater_value}, heater_auto=false")
            else:
                logger.warning(f"Invalid relays.heater value: {relays_cmd['heater']}")
        
        # Map relays.pump to pump_force
        if "pump" in relays_cmd:
            pump_value = normalize_relay_value(relays_cmd["pump"])
            if pump_value:
                desired_state["pump_force"] = pump_value
                logger.info(f"Mapped relays.pump={relays_cmd['pump']} -> pump_force={pump_value}")
            else:
                logger.warning(f"Invalid relays.pump value: {relays_cmd['pump']}")
        
        # Map relays.lights to lights_mode (optional)
        if "lights" in relays_cmd:
            lights_value = normalize_relay_value(relays_cmd["lights"])
            if lights_value:
                desired_state["lights_mode"] = lights_value
                logger.info(f"Mapped relays.lights={relays_cmd['lights']} -> lights_mode={lights_value}")
    
    # =========================================================================
    # STEP 2: Apply settings with verification
    # =========================================================================
    
    try:
        # Heater control with automation (TASK 5)
        heater_auto = desired_state.get("heater_auto", False)
        heater_force = desired_state.get("heater_force", "auto")
        heater_on_below_c = desired_state.get("heater_on_below_c", 5.0)
        heater_off_above_c = desired_state.get("heater_off_above_c", 23.0)
        
        # Validate thresholds (must have hysteresis)
        if heater_on_below_c >= heater_off_above_c:
            logger.warning(f"Invalid heater thresholds: on_below={heater_on_below_c} >= off_above={heater_off_above_c}, ignoring auto mode")
            heater_auto = False
        
        # Get current heater state
        relays = read_relay_states()
        current_heater_state = relays.get("heater", {}).get("state", "unknown") if relays else "unknown"
        
        # Check minimum hold time (only for AUTO mode)
        last_change_ts = None
        if state_manager:
            last_change_ts = state_manager.get_last_relay_change("heater")
        
        time_since_change = None
        if last_change_ts:
            time_since_change = pytime.time() - last_change_ts
        
        # Determine desired heater state and mode (MANUAL vs AUTO)
        desired_heater_state = None
        reason = None
        is_manual_override = False  # MANUAL overrides apply immediately (no hold-time)
        
        if heater_force == "on":
            desired_heater_state = True
            reason = "forced ON"
            is_manual_override = True  # MANUAL: no hold-time
        
        elif heater_force == "off":
            desired_heater_state = False
            reason = "forced OFF"
            is_manual_override = True  # MANUAL: no hold-time
        
        elif (heater_force == "auto" or heater_force not in ("on", "off")) and heater_auto:
            # Automatic heater control based on temperature (AUTO mode: with hold-time)
            temp = read_temperature()
            if temp is not None:
                if temp < heater_on_below_c:
                    desired_heater_state = True
                    reason = f"auto ON (temp {temp:.1f}°C < {heater_on_below_c}°C)"
                    is_manual_override = False  # AUTO: enforce hold-time
                elif temp > heater_off_above_c:
                    desired_heater_state = False
                    reason = f"auto OFF (temp {temp:.1f}°C > {heater_off_above_c}°C)"
                    is_manual_override = False  # AUTO: enforce hold-time
                else:
                    # In hysteresis range - keep current state
                    reason = f"auto HOLD (temp {temp:.1f}°C in range [{heater_on_below_c}°C - {heater_off_above_c}°C])"
            else:
                logger.warning("Cannot apply heater auto: temperature unavailable")
        
        # Apply heater state change if needed
        if desired_heater_state is not None:
            # Check if state actually needs to change
            current_is_on = current_heater_state == "on"
            
            if desired_heater_state != current_is_on:
                # State needs to change
                # Check hold time ONLY for AUTO mode (not for MANUAL override)
                if not is_manual_override and time_since_change is not None and time_since_change < MIN_HOLD_TIME_S:
                    remaining = MIN_HOLD_TIME_S - time_since_change
                    logger.info(f"Heater AUTO change blocked by hold time: {remaining:.0f}s remaining")
                    actions_taken.append(f"heater {reason} (blocked: {remaining:.0f}s hold time)")
                else:
                    # Apply change (MANUAL applies immediately, AUTO applies after hold-time)
                    if is_manual_override:
                        logger.info(f"Applying MANUAL heater override (no hold-time): {reason}")
                    
                    if apply_heater_setting(desired_heater_state, verify=True):
                        actions_taken.append(f"heater {reason}")
                        # Record change time
                        if state_manager:
                            state_manager.save_relay_change("heater")
                    else:
                        actions_taken.append(f"heater {reason} FAILED")
                        logger.error(f"Heater state change FAILED: desired={desired_heater_state}, reason={reason}")
            else:
                # State already correct
                actions_taken.append(f"heater {reason} (already {current_heater_state})")
        elif reason:
            # No state change needed, just log reason
            actions_taken.append(f"heater {reason}")
        
        # Pump control
        pump_force = desired_state.get("pump_force")
        if pump_force == "on":
            if apply_pump_setting(True, verify=True):
                actions_taken.append("pump forced ON")
            else:
                actions_taken.append("pump forced ON FAILED")
                logger.error("Pump state change FAILED: desired=on")
        elif pump_force == "off":
            if apply_pump_setting(False, verify=True):
                actions_taken.append("pump forced OFF")
            else:
                actions_taken.append("pump forced OFF FAILED")
                logger.error("Pump state change FAILED: desired=off")
        
        # Lights control
        lights_mode = desired_state.get("lights_mode")
        if lights_mode:
            if apply_lighting_mode(lights_mode):
                actions_taken.append(f"lights set to '{lights_mode}'")
            else:
                actions_taken.append(f"lights set to '{lights_mode}' FAILED")
        
        # Log what was done
        if actions_taken:
            logger.info("Actions: %s", ', '.join(actions_taken))
        else:
            logger.info("No actions needed")
        
    except Exception as err:
        apply_failed = True
        apply_error = str(err)
        actions_taken.append(f"FAILED: {apply_error}")
        logger.error("Error applying desired state: %s", apply_error, exc_info=True)
    
    # Build and return current state with FRESH relay states (post-change verification)
    current_state = build_current_state()
    if actions_taken:
        current_state["actions_taken"] = actions_taken
    
    # Include failure flag if apply failed
    if apply_failed:
        current_state["apply_failed"] = True
        current_state["apply_error"] = apply_error
    
    # Log fresh relay states after changes
    if current_state.get("relays"):
        logger.info("Relay states after change (verified): %s", current_state['relays'])
    
    return current_state
