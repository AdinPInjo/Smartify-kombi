"""
Adapters for sensor reading and control functions.
This module provides a clean interface to existing smartify code.

Supports two methods:
1. Direct imports from smartify modules (preferred)
2. HTTP API fallback (if imports fail or modules are not available)
"""

import os
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


def read_gps_location() -> Optional[Dict[str, float]]:
    """
    Read current GPS location
    
    Tries:
    1. Direct import from gps_logger module
    2. HTTP API fallback to /api/gps/current
    
    Returns:
        Dictionary with 'latitude' and 'longitude' keys, or None if unavailable
    """
    # Try direct import first
    try:
        from smartify.gps_logger import get_current_location
        location = get_current_location()
        if location and 'latitude' in location and 'longitude' in location:
            lat = location['latitude']
            lon = location['longitude']
            if lat is not None and lon is not None:
                logger.debug(f"GPS from direct import: {lat}, {lon}")
                return {'latitude': lat, 'longitude': lon}
    except ImportError:
        logger.debug("gps_logger not available, trying HTTP API")
    except Exception as e:
        logger.warning(f"Error reading GPS via import: {e}")
    
    # Fallback to HTTP API
    try:
        url = f"{LOCAL_API_BASE}/api/gps/current"
        response = requests.get(url, timeout=API_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check if GPS data is valid
            if data.get("ok") is False:
                logger.warning(f"HTTP API GPS not available: {data.get('error')}")
                return None
            
            lat = data.get("lat")
            lon = data.get("lon")
            
            if lat is not None and lon is not None:
                logger.debug(f"GPS from HTTP API: {lat}, {lon}")
                return {'latitude': float(lat), 'longitude': float(lon)}
            else:
                logger.warning("HTTP API returned no valid GPS coordinates")
                return None
        else:
            logger.warning(f"HTTP API returned status {response.status_code}")
            return None
    
    except requests.exceptions.RequestException as e:
        logger.warning(f"HTTP API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading GPS via HTTP API: {e}")
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


def apply_heater_setting(enabled: bool) -> bool:
    """
    Enable or disable heater
    
    Args:
        enabled: True to enable, False to disable
    
    Returns:
        True if successful, False otherwise
    """
    state = "on" if enabled else "off"
    return set_relay_state("heater", state, mode="manual")


def apply_pump_setting(enabled: bool) -> bool:
    """
    Enable or disable water pump
    
    Args:
        enabled: True to enable, False to disable
    
    Returns:
        True if successful, False otherwise
    """
    state = "on" if enabled else "off"
    return set_relay_state("pump", state, mode="manual")


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
    Build comprehensive current state snapshot
    
    Returns:
        Dictionary with relays, temps, water, gps, uptime
    """
    current_state = {}
    
    try:
        # Read relay states
        relays = read_relay_states()
        if relays:
            current_state["relays"] = {
                name: data["state"] for name, data in relays.items()
            }
        
        # Read individual temperatures
        temps = read_individual_temperatures()
        if temps:
            current_state["temps"] = temps
        
        # Read water level
        water = read_water_level()
        if water is not None:
            current_state["water_percent"] = water
        
        # Read GPS
        gps = read_gps_location()
        if gps:
            current_state["gps"] = {
                "lat": gps.get("latitude"),
                "lon": gps.get("longitude"),
            }
        
        # Read uptime
        uptime = get_system_uptime()
        if uptime is not None:
            current_state["uptime_s"] = uptime
        
    except Exception as e:
        logger.error(f"Error building current state: {e}")
        current_state["error"] = str(e)
    
    return current_state


def apply_desired_state(desired_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply desired state to device with heater automation rules
    
    Supported desired_state fields:
    - heater_auto: bool (enable automatic heater control)
    - heater_on_below_c: float (turn heater on below this temp)
    - heater_off_above_c: float (turn heater off above this temp)
    - heater_force: "on" | "off" | "auto" (override auto mode)
    - pump_force: "on" | "off"
    - lights_mode: "off" | "dim" | "on"
    - gps_enabled: bool (optional, for future use)
    
    Args:
        desired_state: Dictionary with settings
    
    Returns:
        Dictionary with actual current state after applying
    """
    logger.info(f"Applying desired state: {desired_state}")
    
    actions_taken = []
    
    try:
        # Heater control with automation
        heater_auto = desired_state.get("heater_auto", False)
        heater_force = desired_state.get("heater_force", "auto")
        heater_on_below_c = desired_state.get("heater_on_below_c", 5.0)
        heater_off_above_c = desired_state.get("heater_off_above_c", 23.0)
        
        if heater_force == "on":
            # Force heater on
            if apply_heater_setting(True):
                actions_taken.append("heater forced ON")
        
        elif heater_force == "off":
            # Force heater off
            if apply_heater_setting(False):
                actions_taken.append("heater forced OFF")
        
        elif heater_force == "auto" and heater_auto:
            # Automatic heater control based on temperature
            temp = read_temperature()
            if temp is not None:
                if temp < heater_on_below_c:
                    if apply_heater_setting(True):
                        actions_taken.append(f"heater auto ON (temp {temp:.1f}°C < {heater_on_below_c}°C)")
                elif temp > heater_off_above_c:
                    if apply_heater_setting(False):
                        actions_taken.append(f"heater auto OFF (temp {temp:.1f}°C > {heater_off_above_c}°C)")
                else:
                    actions_taken.append(f"heater auto HOLD (temp {temp:.1f}°C in range)")
            else:
                logger.warning("Cannot apply heater auto: temperature unavailable")
        
        # Pump control
        pump_force = desired_state.get("pump_force")
        if pump_force == "on":
            if apply_pump_setting(True):
                actions_taken.append("pump forced ON")
        elif pump_force == "off":
            if apply_pump_setting(False):
                actions_taken.append("pump forced OFF")
        
        # Lights control
        lights_mode = desired_state.get("lights_mode")
        if lights_mode:
            if apply_lighting_mode(lights_mode):
                actions_taken.append(f"lights set to '{lights_mode}'")
        
        # Log what was done
        if actions_taken:
            logger.info(f"Actions: {', '.join(actions_taken)}")
        else:
            logger.info("No actions needed")
        
    except Exception as e:
        logger.error(f"Error applying desired state: {e}", exc_info=True)
    
    # Build and return current state
    current_state = build_current_state()
    if actions_taken:
        current_state["actions_taken"] = actions_taken
    
    return current_state
