import time

from smartify import app as smartify_app


def run_rule_condition_tests() -> None:
    now = int(time.time())
    sensor_snapshots = {
        "kombi": {
            "avg_temp": 10.0,
            "is_ready": True,
            "is_stale": False,
            "age_seconds": 0,
            "sample_count": 6,
        },
        "garaza": {
            "avg_temp": 30.0,
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
        
        # AND/OR nesting
        cond = {
            "op": "and",
            "conditions": [
                {"type": "temperature", "sensor": "kombi", "cmp": ">", "value": 5},
                {"type": "temperature", "sensor": "garaza", "cmp": "<", "value": 35},
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

