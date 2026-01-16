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
# Control Function Adapters
# =============================================================================

def apply_heater_setting(enabled: bool) -> bool:
    """
    Enable or disable heater
    
    Args:
        enabled: True to enable, False to disable
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # TODO: Replace with actual control function
        logger.info(f"Would {'enable' if enabled else 'disable'} heater")
        return True
    except Exception as e:
        logger.error(f"Error setting heater: {e}")
        return False


def apply_pump_setting(enabled: bool) -> bool:
    """
    Enable or disable water pump
    
    Args:
        enabled: True to enable, False to disable
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # TODO: Replace with actual control function
        logger.info(f"Would {'enable' if enabled else 'disable'} pump")
        return True
    except Exception as e:
        logger.error(f"Error setting pump: {e}")
        return False


def apply_lighting_mode(mode: str) -> bool:
    """
    Set lighting mode
    
    Args:
        mode: "off", "dim", or "bright"
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # TODO: Replace with actual control function
        logger.info(f"Would set lighting mode to '{mode}'")
        return True
    except Exception as e:
        logger.error(f"Error setting lighting: {e}")
        return False


def apply_target_temperature(temp_c: float) -> bool:
    """
    Set target temperature
    
    Args:
        temp_c: Target temperature in Celsius
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # TODO: Replace with actual control function
        logger.info(f"Would set target temperature to {temp_c}°C")
        return True
    except Exception as e:
        logger.error(f"Error setting target temperature: {e}")
        return False


# =============================================================================
# Settings Application
# =============================================================================

def apply_desired_state(desired_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply desired state to device
    
    Args:
        desired_state: Dictionary with settings like heaterEnabled, pumpEnabled, etc.
    
    Returns:
        Dictionary with actual current state after applying
    """
    current_state = {}
    
    try:
        # Extract and apply settings
        if "heaterEnabled" in desired_state:
            enabled = desired_state["heaterEnabled"]
            if apply_heater_setting(enabled):
                current_state["heaterEnabled"] = enabled
        
        if "pumpEnabled" in desired_state:
            enabled = desired_state["pumpEnabled"]
            if apply_pump_setting(enabled):
                current_state["pumpEnabled"] = enabled
        
        if "lightingMode" in desired_state:
            mode = desired_state["lightingMode"]
            if apply_lighting_mode(mode):
                current_state["lightingMode"] = mode
        
        if "targetTemperature" in desired_state:
            temp = desired_state["targetTemperature"]
            if apply_target_temperature(temp):
                current_state["targetTemperature"] = temp
        
        # Add current readings to state
        temp = read_temperature()
        if temp is not None:
            current_state["currentTemperature"] = temp
        
        water = read_water_level()
        if water is not None:
            current_state["currentWaterLevel"] = water
        
    except Exception as e:
        logger.error(f"Error applying desired state: {e}")
        current_state["error"] = str(e)
    
    return current_state
