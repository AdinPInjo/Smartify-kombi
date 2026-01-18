import time
from typing import Any, Callable, Dict, Optional, Tuple, List


def _normalize_operator(operator: Any) -> Optional[str]:
    """Normalize operator to canonical symbols. Returns None if invalid."""
    if operator is None:
        return None
    operator_aliases = {
        "below": "<",
        "above": ">",
        "<": "<",
        ">": ">",
        "<=": "<=",
        ">=": ">=",
        "==": "==",
    }
    return operator_aliases.get(str(operator).strip().lower())


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
            return (False, f"invalid cmp/operator '{cmp_raw}', must be one of: <, >, <=, >=, == (or aliases: below, above)", None)
        
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
    """Validate a rule condition payload (composite + range aware)."""
    return _normalize_condition_schema(condition)


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
        min_val = action.get("min")
        max_val = action.get("max")
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


def _evaluate_condition(
    condition: Dict[str, Any],
    get_snapshot: Callable[[str], Optional[Dict[str, Any]]],
) -> Tuple[bool, Optional[str], str, Dict[str, Any]]:
    """Evaluate condition schema. Returns (matched, reason_code, message, snapshot_info)."""
    snapshot_info: Dict[str, Any] = {"snapshot_values": {}, "snapshot_meta": {}}
    
    if not isinstance(condition, dict):
        return (False, "invalid_condition", "Condition must be a dict", snapshot_info)
    
    if "op" in condition:
        op = str(condition.get("op", "")).lower().strip()
        if op in ("and", "or"):
            conditions = condition.get("conditions", [])
            if not isinstance(conditions, list):
                return (False, "invalid_condition", f"{op} conditions must be a list", snapshot_info)
            sub_results = []
            sensor_issue = None
            for sub in conditions:
                matched, reason_code, message, sub_info = _evaluate_condition(sub, get_snapshot)
                sub_results.append(matched)
                snapshot_info["snapshot_values"].update(sub_info.get("snapshot_values", {}))
                snapshot_info["snapshot_meta"].update(sub_info.get("snapshot_meta", {}))
                if reason_code in ("sensor_warming_up", "sensor_stale", "sensor_no_data", "sensor_no_temp", "sensor_no_humidity") and sensor_issue is None:
                    sensor_issue = (reason_code, message)
            matched = all(sub_results) if op == "and" else any(sub_results)
            if not matched and sensor_issue:
                return (False, sensor_issue[0], sensor_issue[1], snapshot_info)
            return (matched, "ok", "Composite condition evaluated", snapshot_info)
        if op == "not":
            sub = condition.get("condition")
            matched, reason_code, message, sub_info = _evaluate_condition(sub, get_snapshot)
            snapshot_info["snapshot_values"].update(sub_info.get("snapshot_values", {}))
            snapshot_info["snapshot_meta"].update(sub_info.get("snapshot_meta", {}))
            if reason_code in ("sensor_warming_up", "sensor_stale", "sensor_no_data", "sensor_no_temp", "sensor_no_humidity"):
                return (False, reason_code, message, snapshot_info)
            return (not matched, "ok", "Negated condition evaluated", snapshot_info)
        return (False, "invalid_condition", f"Unknown op '{op}'", snapshot_info)
    
    condition_type = condition.get("type")
    if condition_type == "always":
        return (True, "ok", "Always true", snapshot_info)
    
    if condition_type not in ("temperature", "humidity", "temperature_between", "humidity_between"):
        return (False, "invalid_condition", f"Unknown condition type '{condition_type}'", snapshot_info)
    
    sensor_name = condition.get("sensor", "")
    if not sensor_name:
        return (False, "invalid_condition", "Condition missing sensor", snapshot_info)
    
    snapshot = get_snapshot(sensor_name)
    if not snapshot:
        return (False, "sensor_no_data", "Rule error: no sensor data", snapshot_info)
    
    sample_count = int(snapshot.get("sample_count", 0) or 0)
    is_ready = snapshot.get("is_ready", False)
    is_stale = snapshot.get("is_stale", False)
    snapshot_temp = snapshot.get("avg_temp")
    snapshot_humidity = snapshot.get("avg_humidity")
    age_seconds = int(snapshot.get("age_seconds", 0) or 0)
    
    snapshot_info["snapshot_values"][sensor_name] = {
        "temp": snapshot_temp,
        "humidity": snapshot_humidity,
    }
    snapshot_info["snapshot_meta"][sensor_name] = {
        "age_seconds": age_seconds,
        "sample_count": sample_count,
        "is_ready": is_ready,
        "is_stale": is_stale,
    }
    
    if not is_ready:
        return (False, "sensor_warming_up", f"Waiting for snapshot… {sample_count}/6", snapshot_info)
    if is_stale:
        age_min = age_seconds // 60
        return (False, "sensor_stale", f"Sensor stale ({age_min} min). Forced OFF.", snapshot_info)
    
    if condition_type in ("temperature", "temperature_between"):
        if snapshot_temp is None:
            return (False, "sensor_no_temp", "Rule error: no temperature value", snapshot_info)
        if condition_type == "temperature_between":
            min_val = float(condition.get("min"))
            max_val = float(condition.get("max"))
            min_inclusive = bool(condition.get("min_inclusive", True))
            max_inclusive = bool(condition.get("max_inclusive", False))
            lower_ok = snapshot_temp >= min_val if min_inclusive else snapshot_temp > min_val
            upper_ok = snapshot_temp <= max_val if max_inclusive else snapshot_temp < max_val
            return (lower_ok and upper_ok, "ok", "Temperature range evaluated", snapshot_info)
        cmp_op = condition.get("cmp", condition.get("operator"))
        normalized_cmp = _normalize_operator(cmp_op)
        if not normalized_cmp:
            return (False, "invalid_condition", f"Invalid cmp/operator '{cmp_op}'", snapshot_info)
        value = condition.get("value")
        if not isinstance(value, (int, float)):
            return (False, "invalid_condition", "Condition value is not numeric", snapshot_info)
        if normalized_cmp == "<":
            matched = snapshot_temp < value
        elif normalized_cmp == ">":
            matched = snapshot_temp > value
        elif normalized_cmp == "<=":
            matched = snapshot_temp <= value
        elif normalized_cmp == ">=":
            matched = snapshot_temp >= value
        elif normalized_cmp == "==":
            matched = snapshot_temp == value
        else:
            return (False, "invalid_condition", f"Invalid cmp/operator '{cmp_op}'", snapshot_info)
        return (matched, "ok", "Temperature comparison evaluated", snapshot_info)
    
    if condition_type in ("humidity", "humidity_between"):
        if snapshot_humidity is None:
            return (False, "sensor_no_humidity", "Rule error: no humidity value", snapshot_info)
        if condition_type == "humidity_between":
            min_val = float(condition.get("min"))
            max_val = float(condition.get("max"))
            min_inclusive = bool(condition.get("min_inclusive", True))
            max_inclusive = bool(condition.get("max_inclusive", False))
            lower_ok = snapshot_humidity >= min_val if min_inclusive else snapshot_humidity > min_val
            upper_ok = snapshot_humidity <= max_val if max_inclusive else snapshot_humidity < max_val
            return (lower_ok and upper_ok, "ok", "Humidity range evaluated", snapshot_info)
        cmp_op = condition.get("cmp", condition.get("operator"))
        normalized_cmp = _normalize_operator(cmp_op)
        if not normalized_cmp:
            return (False, "invalid_condition", f"Invalid cmp/operator '{cmp_op}'", snapshot_info)
        value = condition.get("value")
        if not isinstance(value, (int, float)):
            return (False, "invalid_condition", "Condition value is not numeric", snapshot_info)
        if normalized_cmp == "<":
            matched = snapshot_humidity < value
        elif normalized_cmp == ">":
            matched = snapshot_humidity > value
        elif normalized_cmp == "<=":
            matched = snapshot_humidity <= value
        elif normalized_cmp == ">=":
            matched = snapshot_humidity >= value
        elif normalized_cmp == "==":
            matched = snapshot_humidity == value
        else:
            return (False, "invalid_condition", f"Invalid cmp/operator '{cmp_op}'", snapshot_info)
        return (matched, "ok", "Humidity comparison evaluated", snapshot_info)
    
    return (False, "invalid_condition", "Unknown condition type", snapshot_info)


def evaluate_single_rule(
    rule: Dict[str, Any],
    get_snapshot: Callable[[str], Optional[Dict[str, Any]]],
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Evaluate a single rule and return runtime status."""
    now = int(time.time()) if now is None else int(now)
    if not isinstance(rule, dict):
        return {
            "can_evaluate": False,
            "matched": False,
            "condition_matched": False,
            "can_trigger": False,
            "reason_code": "error",
            "message": "Rule error: invalid rule format (not a dict)",
            "sensor_name": None,
            "snapshot_temp": None,
            "snapshot_humidity": None,
            "threshold": None,
            "operator": None,
            "age_seconds": 0,
            "sample_count": 0,
            "cooldown_remaining": 0,
            "snapshot_values": {},
            "snapshot_meta": {},
        }
    
    if not rule.get("is_enabled", True):
        return {
            "can_evaluate": False,
            "matched": False,
            "condition_matched": False,
            "can_trigger": False,
            "reason_code": "disabled",
            "message": "Rule disabled",
            "sensor_name": None,
            "snapshot_temp": None,
            "snapshot_humidity": None,
            "threshold": None,
            "operator": None,
            "age_seconds": 0,
            "sample_count": 0,
            "cooldown_remaining": 0,
            "snapshot_values": {},
            "snapshot_meta": {},
        }
    
    condition = rule.get("condition", {})
    ok, err, normalized_condition = validate_rule_condition(condition)
    if not ok or normalized_condition is None:
        return {
            "can_evaluate": False,
            "matched": False,
            "condition_matched": False,
            "can_trigger": False,
            "reason_code": "invalid_condition",
            "message": err or "Invalid condition schema",
            "sensor_name": None,
            "snapshot_temp": None,
            "snapshot_humidity": None,
            "threshold": None,
            "operator": None,
            "age_seconds": 0,
            "sample_count": 0,
            "cooldown_remaining": 0,
            "snapshot_values": {},
            "snapshot_meta": {},
        }
    
    normalized_action = None
    ok_action, _action_err, normalized_action = validate_rule_action(rule.get("action"))
    if ok_action and isinstance(normalized_action, dict) and normalized_action.get("type") == "temperature_band":
        band_condition = {
            "type": "temperature_between",
            "sensor": normalized_action.get("sensor"),
            "min": normalized_action.get("min"),
            "max": normalized_action.get("max"),
            "min_inclusive": normalized_action.get("min_inclusive", True),
            "max_inclusive": normalized_action.get("max_inclusive", False),
        }
        ok_band, _band_err, normalized_band = validate_rule_condition(band_condition)
        if ok_band and normalized_band is not None:
            normalized_condition = normalized_band
    
    last_triggered = rule.get("last_triggered_at")
    cooldown_seconds = rule.get("cooldown_seconds", 60)
    cooldown_remaining = 0
    if last_triggered:
        age = now - last_triggered
        if age < cooldown_seconds:
            cooldown_remaining = cooldown_seconds - age
    
    matched, reason_code, message, snapshot_info = _evaluate_condition(normalized_condition, get_snapshot)
    snapshot_values = snapshot_info.get("snapshot_values", {})
    snapshot_meta = snapshot_info.get("snapshot_meta", {})
    
    sensor_name = None
    snapshot_temp = None
    snapshot_humidity = None
    age_seconds = 0
    sample_count = 0
    if len(snapshot_values) == 1:
        sensor_name = next(iter(snapshot_values.keys()))
        sensor_value = snapshot_values.get(sensor_name)
        if isinstance(sensor_value, dict):
            snapshot_temp = sensor_value.get("temp")
            snapshot_humidity = sensor_value.get("humidity")
        else:
            snapshot_temp = sensor_value
        meta = snapshot_meta.get(sensor_name, {})
        age_seconds = int(meta.get("age_seconds", 0) or 0)
        sample_count = int(meta.get("sample_count", 0) or 0)
    
    operator = None
    threshold = None
    min_val = None
    max_val = None
    min_inclusive = None
    max_inclusive = None
    condition_type = normalized_condition.get("type") if isinstance(normalized_condition, dict) else None
    if condition_type in ("temperature", "humidity"):
        operator = normalized_condition.get("cmp", normalized_condition.get("operator"))
        threshold = normalized_condition.get("value")
    elif condition_type in ("temperature_between", "humidity_between"):
        min_val = normalized_condition.get("min")
        max_val = normalized_condition.get("max")
        min_inclusive = normalized_condition.get("min_inclusive")
        max_inclusive = normalized_condition.get("max_inclusive")
    
    condition_matched = matched
    can_trigger = condition_matched and reason_code == "ok" and cooldown_remaining == 0
    if condition_matched and cooldown_remaining > 0:
        reason_code = "cooldown"
        message = f"Cooldown… {cooldown_remaining}s"
    
    if normalized_action and normalized_action.get("type") == "temperature_band":
        if snapshot_temp is not None and min_val is not None and max_val is not None:
            message = f"{sensor_name} {snapshot_temp:.1f}°C in [{min_val},{max_val}] => {'on' if condition_matched else 'off'}"
    
    return {
        "can_evaluate": True,
        "matched": condition_matched,
        "condition_matched": condition_matched,
        "can_trigger": can_trigger,
        "reason_code": reason_code,
        "message": message,
        "sensor_name": sensor_name,
        "snapshot_temp": snapshot_temp,
        "snapshot_humidity": snapshot_humidity,
        "threshold": threshold,
        "operator": operator,
        "min": min_val,
        "max": max_val,
        "min_inclusive": min_inclusive,
        "max_inclusive": max_inclusive,
        "age_seconds": age_seconds,
        "sample_count": sample_count,
        "cooldown_remaining": cooldown_remaining,
        "snapshot_values": snapshot_values,
        "snapshot_meta": snapshot_meta,
    }


def evaluate_rules(
    rules: List[Dict[str, Any]],
    get_snapshot: Callable[[str], Optional[Dict[str, Any]]],
    current_state: Optional[str] = None,
    now: Optional[int] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool, Optional[str]]:
    """Deterministically evaluate enabled rules and return winner info."""
    now = int(time.time()) if now is None else int(now)
    enabled_rules = [r for r in rules if isinstance(r, dict) and r.get("is_enabled", True)]
    
    if not enabled_rules:
        return ("off", None, None, True, "no_rules")
    
    candidates = []
    for rule in enabled_rules:
        condition = rule.get("condition", {})
        ok, _err, normalized_condition = validate_rule_condition(condition)
        if not ok or normalized_condition is None:
            continue
        
        ok_action, _err, normalized_action = validate_rule_action(rule.get("action"))
        if ok_action and isinstance(normalized_action, dict) and normalized_action.get("type") == "temperature_band":
            band_condition = {
                "type": "temperature_between",
                "sensor": normalized_action.get("sensor"),
                "min": normalized_action.get("min"),
                "max": normalized_action.get("max"),
                "min_inclusive": normalized_action.get("min_inclusive", True),
                "max_inclusive": normalized_action.get("max_inclusive", False),
            }
            ok_band, _band_err, normalized_band = validate_rule_condition(band_condition)
            if ok_band and normalized_band is not None:
                normalized_condition = normalized_band
        
        matched, reason_code, message, snapshot_info = _evaluate_condition(normalized_condition, get_snapshot)
        if reason_code in ("sensor_warming_up", "sensor_stale", "sensor_no_data", "sensor_no_temp", "sensor_no_humidity"):
            hold_state = current_state if current_state in ("on", "off") else "off"
            return (hold_state, None, None, False, reason_code)
        
        if not matched:
            continue
        
        if not ok_action or normalized_action is None:
            continue
        
        candidates.append((rule, normalized_action, snapshot_info))
    
    if not candidates:
        return ("off", None, None, True, "no_match")
    
    def _candidate_sort_key(candidate: Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]) -> Tuple[int, int, int, str]:
        rule, _action, _snapshot = candidate
        priority = int(rule.get("priority", 100) or 100)
        created_at = int(rule.get("created_at", 0) or 0)
        rule_id = str(rule.get("id", ""))
        return (-priority, created_at, 0, rule_id)
    
    candidates.sort(key=_candidate_sort_key)
    winner_rule, winner_action, winner_snapshot = candidates[0]
    
    desired_state = None
    if winner_action.get("type") == "set_state":
        desired_state = winner_action.get("state")
    elif winner_action.get("type") == "temperature_band":
        sensor = winner_action.get("sensor", "")
        snapshot = get_snapshot(sensor) if sensor else None
        if not snapshot or not isinstance(snapshot, dict):
            hold_state = current_state if current_state in ("on", "off") else "off"
            return (hold_state, winner_rule, {"action": winner_action, "snapshot": winner_snapshot}, False, "sensor_no_data")
        if not snapshot.get("is_ready", False):
            hold_state = current_state if current_state in ("on", "off") else "off"
            return (hold_state, winner_rule, {"action": winner_action, "snapshot": winner_snapshot}, False, "sensor_warming_up")
        if snapshot.get("is_stale", False):
            hold_state = current_state if current_state in ("on", "off") else "off"
            return (hold_state, winner_rule, {"action": winner_action, "snapshot": winner_snapshot}, False, "sensor_stale")
        temp = snapshot.get("avg_temp")
        if temp is None:
            hold_state = current_state if current_state in ("on", "off") else "off"
            return (hold_state, winner_rule, {"action": winner_action, "snapshot": winner_snapshot}, False, "sensor_no_data")
        min_val = float(winner_action.get("min"))
        max_val = float(winner_action.get("max"))
        min_inclusive = bool(winner_action.get("min_inclusive", True))
        max_inclusive = bool(winner_action.get("max_inclusive", False))
        lower_ok = temp >= min_val if min_inclusive else temp > min_val
        upper_ok = temp <= max_val if max_inclusive else temp < max_val
        desired_state = winner_action.get("on_state") if (lower_ok and upper_ok) else winner_action.get("else_state")
    else:
        desired_state = "off"
    
    return (desired_state, winner_rule, {"action": winner_action, "snapshot": winner_snapshot}, True, None)

