import time

from smartify import rule_engine


def run_rule_condition_tests() -> None:
    now = int(time.time())
    sensor_snapshots = {
        "kombi": {
            "avg_temp": 10.0,
            "avg_humidity": 45.0,
            "is_ready": True,
            "is_stale": False,
            "age_seconds": 0,
            "sample_count": 6,
        },
        "garaza": {
            "avg_temp": 30.0,
            "avg_humidity": 40.0,
            "is_ready": True,
            "is_stale": False,
            "age_seconds": 0,
            "sample_count": 6,
        },
    }
    
    def get_snapshot(sensor_name: str):
        return sensor_snapshots.get(sensor_name)
    
    rules = [
        {
            "id": "rule-high",
            "relay_id": "relay-test",
            "name": "High Priority OFF",
            "condition": {"type": "temperature", "sensor": "kombi", "cmp": ">", "value": 5},
            "action": {"type": "set_state", "state": "off"},
            "priority": 100,
            "cooldown_seconds": 60,
            "is_enabled": True,
            "last_triggered_at": None,
            "created_at": 1,
        },
        {
            "id": "rule-low",
            "relay_id": "relay-test",
            "name": "Low Priority ON",
            "condition": {"type": "temperature", "sensor": "kombi", "cmp": ">", "value": 5},
            "action": {"type": "set_state", "state": "on"},
            "priority": 90,
            "cooldown_seconds": 60,
            "is_enabled": True,
            "last_triggered_at": None,
            "created_at": 2,
        },
    ]
    
    # Range condition edges
    cond = {
        "type": "temperature",
        "sensor": "kombi",
        "between": {"min": 5, "max": 20, "min_inclusive": True, "max_inclusive": False},
    }
    ok, _, normalized = rule_engine.validate_rule_condition(cond)
    assert ok and normalized, "Expected range condition to validate"
    matched, reason_code, _, _ = rule_engine._evaluate_condition(normalized, get_snapshot)
    assert matched and reason_code == "ok", "Expected range condition to match at 10°C"
    
    # Humidity comparison
    cond = {"type": "humidity", "sensor": "kombi", "operator": ">", "value": 30}
    ok, _, normalized = rule_engine.validate_rule_condition(cond)
    matched, _, _, _ = rule_engine._evaluate_condition(normalized, get_snapshot)
    assert matched, "Expected humidity comparison to match"
    
    # Humidity range
    cond = {
        "type": "humidity_between",
        "sensor": "kombi",
        "min": 20,
        "max": 60,
        "min_inclusive": True,
        "max_inclusive": False,
    }
    ok, _, normalized = rule_engine.validate_rule_condition(cond)
    matched, _, _, _ = rule_engine._evaluate_condition(normalized, get_snapshot)
    assert matched, "Expected humidity range to match"
    
    # AND/OR nesting
    cond = {
        "op": "and",
        "conditions": [
            {"type": "temperature", "sensor": "kombi", "cmp": ">", "value": 5},
            {"type": "humidity", "sensor": "garaza", "cmp": "<", "value": 50},
        ],
    }
    ok, _, normalized = rule_engine.validate_rule_condition(cond)
    matched, _, _, _ = rule_engine._evaluate_condition(normalized, get_snapshot)
    assert matched, "Expected AND condition to match"
    
    cond = {
        "op": "or",
        "conditions": [
            {"type": "temperature", "sensor": "kombi", "cmp": "<", "value": 5},
            {"type": "temperature", "sensor": "garaza", "cmp": ">", "value": 25},
        ],
    }
    ok, _, normalized = rule_engine.validate_rule_condition(cond)
    matched, _, _, _ = rule_engine._evaluate_condition(normalized, get_snapshot)
    assert matched, "Expected OR condition to match"
    
    # Deterministic winner by priority
    desired_state, winner_rule, _winner_info, _sensor_ok, _reason = rule_engine.evaluate_rules(rules, get_snapshot, current_state="on", now=now)
    assert desired_state == "off", "Expected highest priority rule to set OFF"
    assert winner_rule and winner_rule.get("id") == "rule-high", "Expected rule-high to win"
    
    # Cooldown evaluation in runtime_status
    cooldown_rule = dict(rules[0])
    cooldown_rule["last_triggered_at"] = now
    cooldown_rule["cooldown_seconds"] = 120
    status = rule_engine.evaluate_single_rule(cooldown_rule, get_snapshot, now=now + 30)
    assert status.get("reason_code") == "cooldown", "Expected cooldown reason"
    assert status.get("cooldown_remaining") == 90, "Expected cooldown_remaining=90"
    
    # Sensor unavailable should HOLD desired_state
    sensor_snapshots["kombi"]["is_ready"] = False
    desired_state, _winner, _info, sensor_ok, reason = rule_engine.evaluate_rules(rules, get_snapshot, current_state="on", now=now)
    assert desired_state == "on", "Expected hold last desired_state on sensor unavailable"
    assert not sensor_ok and reason == "sensor_warming_up", "Expected sensor_warming_up reason"
    
    # temperature_band runtime_status mapping
    band_rule = {
        "id": "rule-band",
        "relay_id": "relay-test",
        "name": "Band Rule",
        "condition": {"type": "always"},
        "action": {
            "type": "temperature_band",
            "sensor": "kombi",
            "min": 5,
            "max": 20,
            "min_inclusive": True,
            "max_inclusive": False,
            "on_state": "on",
            "else_state": "off",
        },
        "priority": 50,
        "cooldown_seconds": 60,
        "is_enabled": True,
        "last_triggered_at": None,
        "created_at": 3,
    }
    sensor_snapshots["kombi"]["is_ready"] = True
    status = rule_engine.evaluate_single_rule(band_rule, get_snapshot, now=now)
    assert status.get("sensor_name") == "kombi", "Expected runtime_status sensor_name for temperature_band"
    assert status.get("snapshot_temp") is not None, "Expected snapshot_temp for temperature_band"
    
    # Multi-relay independence
    rules_relay1 = [
        {
            "id": "rule-r1",
            "relay_id": "relay-1",
            "name": "Relay1 ON",
            "condition": {"type": "temperature", "sensor": "kombi", "cmp": ">", "value": 5},
            "action": {"type": "set_state", "state": "on"},
            "priority": 50,
            "cooldown_seconds": 60,
            "is_enabled": True,
            "last_triggered_at": None,
            "created_at": 1,
        }
    ]
    rules_relay2 = [
        {
            "id": "rule-r2",
            "relay_id": "relay-2",
            "name": "Relay2 OFF",
            "condition": {"type": "temperature", "sensor": "kombi", "cmp": ">", "value": 5},
            "action": {"type": "set_state", "state": "off"},
            "priority": 50,
            "cooldown_seconds": 60,
            "is_enabled": True,
            "last_triggered_at": None,
            "created_at": 1,
        }
    ]
    desired_state_1, _, _, _, _ = rule_engine.evaluate_rules(rules_relay1, get_snapshot, current_state="off", now=now)
    desired_state_2, _, _, _, _ = rule_engine.evaluate_rules(rules_relay2, get_snapshot, current_state="on", now=now)
    assert desired_state_1 == "on" and desired_state_2 == "off", "Expected relay-specific rules to apply"
    
    print("PASS: Composite conditions, deterministic winner, cooldown, and hold-state checks.")


if __name__ == "__main__":
    run_rule_condition_tests()

