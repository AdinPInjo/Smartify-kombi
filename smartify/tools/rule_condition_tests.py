import time

from smartify import app as smartify_app


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
    
    relay_id = "relay-test"
    relay_state = {
        "mode": "auto",
        "actual_state": "on",
        "desired_state": "on",
        "last_applied_at": now,
        "manual_until": None,
    }
    relay_device = {
        "id": relay_id,
        "name": "heater",
        "pin": 17,
        "active_low": 0,
        "is_enabled": True,
        "min_on_seconds": 60,
        "min_off_seconds": 0,
    }
    
    def fake_get_sensor_snapshot(sensor_name: str):
        return sensor_snapshots.get(sensor_name)
    
    def fake_db_list_relay_rules(_relay_id: str):
        return [
            {
                "id": "rule-high",
                "relay_id": relay_id,
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
                "relay_id": relay_id,
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
    
    def fake_db_get_relay_state_new(_relay_id: str):
        return relay_state
    
    def fake_db_get_relay_device(_relay_id: str):
        return relay_device
    
    def fake_db_update_relay_state_new(_relay_id: str, **kwargs):
        relay_state.update(kwargs)
    
    def fake_db_log_relay_event(*_args, **_kwargs):
        return None
    
    apply_calls = []
    
    def fake_apply_relay_hardware(_relay_id: str, _desired_state: str):
        apply_calls.append(_desired_state)
        return {"ok": True, "state": _desired_state}
    
    originals = {
        "get_sensor_snapshot": smartify_app.get_sensor_snapshot,
        "db_list_relay_rules": smartify_app.db_list_relay_rules,
        "db_get_relay_state_new": smartify_app.db_get_relay_state_new,
        "db_get_relay_device": smartify_app.db_get_relay_device,
        "db_update_relay_state_new": smartify_app.db_update_relay_state_new,
        "db_log_relay_event": smartify_app.db_log_relay_event,
        "apply_relay_hardware": smartify_app.apply_relay_hardware,
    }
    
    try:
        smartify_app.get_sensor_snapshot = fake_get_sensor_snapshot
        smartify_app.db_list_relay_rules = fake_db_list_relay_rules
        smartify_app.db_get_relay_state_new = fake_db_get_relay_state_new
        smartify_app.db_get_relay_device = fake_db_get_relay_device
        smartify_app.db_update_relay_state_new = fake_db_update_relay_state_new
        smartify_app.db_log_relay_event = fake_db_log_relay_event
        smartify_app.apply_relay_hardware = fake_apply_relay_hardware
        
        # Range condition edges
        cond = {
            "type": "temperature",
            "sensor": "kombi",
            "between": {"min": 5, "max": 20, "min_inclusive": True, "max_inclusive": False},
        }
        ok, _, normalized = smartify_app.validate_rule_condition(cond)
        assert ok and normalized, "Expected range condition to validate"
        matched, reason_code, _, _ = smartify_app._evaluate_condition(normalized)
        assert matched and reason_code == "ok", "Expected range condition to match at 10°C"

        # Humidity comparison
        cond = {
            "type": "humidity",
            "sensor": "kombi",
            "operator": ">",
            "value": 30,
        }
        ok, _, normalized = smartify_app.validate_rule_condition(cond)
        matched, _, _, _ = smartify_app._evaluate_condition(normalized)
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
        ok, _, normalized = smartify_app.validate_rule_condition(cond)
        matched, _, _, _ = smartify_app._evaluate_condition(normalized)
        assert matched, "Expected humidity range to match"
        
        # AND/OR nesting
        cond = {
            "op": "and",
            "conditions": [
                {"type": "temperature", "sensor": "kombi", "cmp": ">", "value": 5},
                {"type": "humidity", "sensor": "garaza", "cmp": "<", "value": 50},
            ],
        }
        ok, _, normalized = smartify_app.validate_rule_condition(cond)
        matched, _, _, _ = smartify_app._evaluate_condition(normalized)
        assert matched, "Expected AND condition to match"
        
        cond = {
            "op": "or",
            "conditions": [
                {"type": "temperature", "sensor": "kombi", "cmp": "<", "value": 5},
                {"type": "temperature", "sensor": "garaza", "cmp": ">", "value": 25},
            ],
        }
        ok, _, normalized = smartify_app.validate_rule_condition(cond)
        matched, _, _, _ = smartify_app._evaluate_condition(normalized)
        assert matched, "Expected OR condition to match"
        
        # Deterministic winner by priority
        desired_state, winner_rule, _winner_info, _sensor_ok, _reason = smartify_app.evaluate_rules(relay_id)
        assert desired_state == "off", "Expected highest priority rule to set OFF"
        assert winner_rule and winner_rule.get("id") == "rule-high", "Expected rule-high to win"
        
        # Anti-flap (min_on_seconds) should block OFF apply
        smartify_app.reconcile_relay(relay_id, force=True)
        assert relay_state.get("actual_state") == "on", "Expected relay to remain ON due to min_on_seconds"
        assert not apply_calls, "Expected no hardware apply due to relay cooldown"

        # Sensor unavailable should HOLD desired_state (no forced OFF)
        sensor_snapshots["kombi"]["is_ready"] = False
        relay_state["desired_state"] = "on"
        relay_state["actual_state"] = "on"
        smartify_app.reconcile_relay(relay_id, force=True)
        assert relay_state.get("desired_state") == "on", "Expected desired_state to remain ON when sensor unavailable"
        assert relay_state.get("actual_state") == "on", "Expected actual_state to remain ON when sensor unavailable"

        # temperature_band action should populate runtime_status sensor fields
        band_rule = {
            "id": "rule-band",
            "relay_id": relay_id,
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
        runtime_status = smartify_app.evaluate_single_rule(band_rule, relay_id)
        assert runtime_status.get("sensor_name") == "kombi", "Expected runtime_status sensor_name for temperature_band"
        assert runtime_status.get("snapshot_temp") is not None, "Expected snapshot_temp for temperature_band"

        # Multi-relay independence
        def fake_db_list_relay_rules_multi(target_relay_id: str):
            if target_relay_id == "relay-1":
                return [
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
            return [
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
        
        smartify_app.db_list_relay_rules = fake_db_list_relay_rules_multi
        desired_state_1, _, _, _, _ = smartify_app.evaluate_rules("relay-1")
        desired_state_2, _, _, _, _ = smartify_app.evaluate_rules("relay-2")
        assert desired_state_1 == "on" and desired_state_2 == "off", "Expected relay-specific rules to apply"
        
        print("PASS: Composite conditions, deterministic winner, and anti-flap checks.")
    finally:
        smartify_app.get_sensor_snapshot = originals["get_sensor_snapshot"]
        smartify_app.db_list_relay_rules = originals["db_list_relay_rules"]
        smartify_app.db_get_relay_state_new = originals["db_get_relay_state_new"]
        smartify_app.db_get_relay_device = originals["db_get_relay_device"]
        smartify_app.db_update_relay_state_new = originals["db_update_relay_state_new"]
        smartify_app.db_log_relay_event = originals["db_log_relay_event"]
        smartify_app.apply_relay_hardware = originals["apply_relay_hardware"]


if __name__ == "__main__":
    run_rule_condition_tests()

