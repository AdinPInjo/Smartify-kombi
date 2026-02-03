"""
Utility functions for Smartify.
"""
import json
from typing import Any
import logging

logger = logging.getLogger(__name__)


def coerce_to_dict(value: Any, *, context: str = "") -> dict:
    """
    Normalize user/db JSON-ish values into a dict safely.
    Accepts dict, JSON string, list/tuple of pairs, list of dicts.
    If value is list of strings or plain string that isn't JSON object, return {} and log warning.
    Never raises ValueError from dict(value).
    
    Args:
        value: The value to coerce to dict
        context: Context string for logging (e.g., "rule.params", "pending_state")
    
    Returns:
        dict: The coerced dictionary, or empty dict if coercion fails
    """
    # None -> empty dict
    if value is None:
        return {}
    
    # Already a dict -> return as-is
    if isinstance(value, dict):
        return value
    
    # String -> try JSON parse
    if isinstance(value, str):
        # Empty string -> empty dict
        if not value.strip():
            return {}
        
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
            else:
                # JSON parsed but not a dict (e.g., list, string, number)
                print(f"[coerce_to_dict] Invalid dict-like payload for {context}: "
                      f"JSON parsed to {type(parsed).__name__}, not dict (value={value[:100]}...)")
                return {}
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            # Not valid JSON - could be a plain string like "heater" or "force"
            print(f"[coerce_to_dict] Invalid dict-like payload for {context}: "
                  f"got type=str value='{value[:100]}' (not valid JSON, dropping)")
            return {}
    
    # List or tuple -> try to convert
    if isinstance(value, (list, tuple)):
        # Empty list/tuple -> empty dict
        if not value:
            return {}
        
        # Check if all items are dicts -> merge them
        if all(isinstance(item, dict) for item in value):
            result = {}
            for item in value:
                result.update(item)
            return result
        
        # Check if all items are 2-element sequences (key-value pairs)
        # CRITICAL: Exclude strings! Strings have __len__ but dict(['force']) crashes
        # with "ValueError: dictionary update sequence element #0 has length 5; 2 is required"
        try:
            # Verify items are sequences (tuple/list) but NOT strings, and have exactly length 2
            if all(
                not isinstance(item, str) and 
                hasattr(item, '__len__') and 
                len(item) == 2 
                for item in value
            ):
                return dict(value)
        except (TypeError, ValueError) as e:
            # This should never happen now, but keep defensive catch
            print(f"[coerce_to_dict] Unexpected error converting list to dict for {context}: {e}")
            pass
        
        # List of non-dict, non-pairs (e.g., list of strings)
        sample = value[:3] if len(value) > 3 else value
        print(f"[coerce_to_dict] Invalid dict-like payload for {context}: "
              f"got type=list with non-dict items (sample={sample}, dropping)")
        return {}
    
    # Other types (int, float, bool, etc.) -> log warning and return empty dict
    print(f"[coerce_to_dict] Invalid dict-like payload for {context}: "
          f"got type={type(value).__name__} value={repr(value)[:100]} (dropping)")
    return {}

