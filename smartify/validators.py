"""
Rule validation functions for Smartify relay automation.
Validates and normalizes rule conditions and actions.
"""
from typing import Any, Dict, Optional, Tuple


def _normalize_operator(operator: str) -> str:
    """Normalize comparison operator aliases to standard form."""
    operator_aliases = {
        "above": ">",
        "below": "<",
        "greater": ">",
        "less": "<",
        "eq": "==",
        "equals": "==",
        "gte": ">=",
        "lte": "<=",
        "gt": ">",
        "lt": "<",
    }
    return operator_aliases.get(str(operator).strip().lower(), str(operator).strip())


def _normalize_condition_schema(condition: Any) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Normalize and validate composite/range condition schema."""
    if not isinstance(condition, dict):
        preview = repr(condition)[:120]
        return (False, f"condition must be a dict, got {type(condition).__name__}: {preview}", None)
    
    # Support both {op: "and"} and {"and": [...]} style
    if "op" in condition or "and" in condition or "or" in condition or "not" in condition:
        op = condition.get("op")
        if op is None:
            if "and" in condition:
                op = "and"
                condition = {"op": "and", "conditions": condition.get("and")}
            elif "or" in condition:
                op = "or"
                condition = {"op": "or", "conditions": condition.get("or")}
            elif "not" in condition:
                op = "not"
                condition = {"op": "not", "condition": condition.get("not")}
        op = str(op).lower().strip()
        if op in ("and", "or"):
            conditions = condition.get("conditions", [])
            if not isinstance(conditions, list):
                return (False, f"{op} conditions must be a list", None)
            normalized_list = []
            for sub in conditions:
                ok, err, normalized = _normalize_condition_schema(sub)
                if not ok:
                    return (False, err, None)
                normalized_list.append(normalized)
            return (True, None, {"op": op, "conditions": normalized_list})
        if op == "not":
            sub = condition.get("condition")
            ok, err, normalized = _normalize_condition_schema(sub)
            if not ok:
                return (False, err, None)
            return (True, None, {"op": "not", "condition": normalized})
        return (False, f"unknown op '{op}'", None)
    
    condition_type = condition.get("type")
    if not condition_type:
        return (False, "condition missing required field: type", None)
    
    if condition_type == "always":
        return (True, None, {"type": "always"})
    
    if condition_type in ("temperature", "humidity"):
        sensor = condition.get("sensor")
        if not sensor:
            return (False, f"{condition_type} condition missing required field: sensor", None)
        sensor = str(sensor)
        if sensor not in ("kombi", "garaza"):
            return (False, f"unknown sensor '{sensor}'", None)
        
        if "between" in condition and isinstance(condition.get("between"), dict):
            between = condition.get("between") or {}
            min_val = between.get("min")
            max_val = between.get("max")
            if not isinstance(min_val, (int, float)) or not isinstance(max_val, (int, float)):
                return (False, "between.min and between.max must be numbers", None)
            if min_val >= max_val:
                return (False, "between.min must be less than between.max", None)
            min_inclusive = bool(between.get("min_inclusive", True))
            max_inclusive = bool(between.get("max_inclusive", False))
            if condition_type == "humidity" and (min_val < 0 or max_val > 100):
                return (False, "humidity between range must be within 0..100", None)
            normalized = {
                "type": f"{condition_type}_between",
                "sensor": sensor,
                "min": float(min_val),
                "max": float(max_val),
                "min_inclusive": min_inclusive,
                "max_inclusive": max_inclusive,
            }
            return (True, None, normalized)
        
        cmp_raw = condition.get("cmp", condition.get("operator"))
        normalized_cmp = _normalize_operator(cmp_raw)
        if not normalized_cmp:
            return (False, f"invalid cmp/operator '{cmp_raw}', must be one of: <, >, <=, >= (or aliases: below, above)", None)
        
        value = condition.get("value")
        if not isinstance(value, (int, float)):
            return (False, f"value must be a number, got {type(value).__name__}", None)
        if condition_type == "humidity" and (value < 0 or value > 100):
            return (False, "humidity value must be within 0..100", None)
        
        normalized = {
            "type": condition_type,
            "sensor": sensor,
            "cmp": normalized_cmp,
            "value": float(value),
        }
        return (True, None, normalized)
    
    if condition_type in ("temperature_between", "humidity_between"):
        sensor = condition.get("sensor")
        if not sensor:
            return (False, f"{condition_type} missing required field: sensor", None)
        sensor = str(sensor)
        if sensor not in ("kombi", "garaza"):
            return (False, f"unknown sensor '{sensor}'", None)
        min_val = condition.get("min")
        max_val = condition.get("max")
        if not isinstance(min_val, (int, float)) or not isinstance(max_val, (int, float)):
            return (False, "min and max must be numbers", None)
        if min_val >= max_val:
            return (False, "min must be less than max", None)
        min_inclusive = bool(condition.get("min_inclusive", True))
        max_inclusive = bool(condition.get("max_inclusive", False))
        if condition_type == "humidity_between" and (min_val < 0 or max_val > 100):
            return (False, "humidity between range must be within 0..100", None)
        return (True, None, {
            "type": condition_type,
            "sensor": sensor,
            "min": float(min_val),
            "max": float(max_val),
            "min_inclusive": min_inclusive,
            "max_inclusive": max_inclusive,
        })
    
    return (False, f"unknown condition type '{condition_type}'", None)


def validate_rule_condition(condition: Any) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Validate a rule condition payload (composite + range aware).
    Returns: (is_valid, error_message, normalized_condition)
    """
    ok, err, normalized = _normalize_condition_schema(condition)
    if not ok:
        preview = repr(condition)[:120]
        print(f"[validate_rule_condition] invalid condition: {err} -> {preview}")
    return (ok, err, normalized)


def validate_rule_action(action: Any) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Validate and normalize rule action schema (set_state / temperature_band)."""
    if isinstance(action, str):
        action = action.strip()
        if action == "turn_on":
            return (True, None, {"type": "set_state", "state": "on"})
        if action == "turn_off":
            return (True, None, {"type": "set_state", "state": "off"})
        return (False, f"invalid action '{action}'", None)
    
    if not isinstance(action, dict):
        return (False, f"action must be a dict, got {type(action).__name__}", None)
    
    action_type = action.get("type")
    if action_type == "set_state":
        state = action.get("state")
        if state not in ("on", "off"):
            return (False, "set_state action requires state 'on' or 'off'", None)
        return (True, None, {"type": "set_state", "state": state})
    
    if action_type == "temperature_band":
        sensor = action.get("sensor")
        min_val = action.get("min", action.get("on_min"))
        max_val = action.get("max", action.get("off_max"))
        if not sensor:
            return (False, "temperature_band action missing required field: sensor", None)
        if not isinstance(min_val, (int, float)) or not isinstance(max_val, (int, float)):
            return (False, "temperature_band requires numeric min/max", None)
        min_inclusive = bool(action.get("min_inclusive", True))
        max_inclusive = bool(action.get("max_inclusive", False))
        on_state = action.get("on_state", "on")
        else_state = action.get("else_state", "off")
        if on_state not in ("on", "off") or else_state not in ("on", "off"):
            return (False, "temperature_band states must be 'on' or 'off'", None)
        normalized = {
            "type": "temperature_band",
            "sensor": str(sensor),
            "min": float(min_val),
            "max": float(max_val),
            "min_inclusive": min_inclusive,
            "max_inclusive": max_inclusive,
            "on_state": on_state,
            "else_state": else_state,
        }
        return (True, None, normalized)
    
    return (False, f"unknown action type '{action_type}'", None)

