import time

from smartify import app as smartify_app


def run_rule_engine_debug() -> None:
    relay_id = "relay-heater-test"
    now = int(time.time())
    
    rules = [
        {
            "id": "rule-proba-1",
            "relay_id": relay_id,
            "name": "Proba 1 Kombi",
            "condition": {"type": "temperature", "sensor": "kombi", "operator": ">", "value": 5},
            "action": "turn_on",
            "priority": 96,
            "cooldown_seconds": 60,
            "is_enabled": True,
            "last_triggered_at": None,
            "created_at": 1,
        },
        {
            "id": "rule-kombi-off",
            "relay_id": relay_id,
            "name": "KOMBI OF",
            "condition": {"type": "temperature", "sensor": "kombi", "operator": ">", "value": 20},
            "action": "turn_off",
            "priority": 99,
            "cooldown_seconds": 60,
            "is_enabled": True,
            "last_triggered_at": None,
            "created_at": 2,
        },
        {
            "id": "rule-ugasi",
            "relay_id": relay_id,
            "name": "UGASI",
            "condition": {"type": "temperature", "sensor": "garaza", "operator": ">", "value": 20},
            "action": "turn_off",
            "priority": 100,
            "cooldown_seconds": 60,
            "is_enabled": True,
            "last_triggered_at": None,
            "created_at": 3,
        },
    ]
    
    sensor_snapshots = {
        "kombi": {
            "avg_temp": 21.6,
            "is_ready": True,
            "is_stale": False,
            "age_seconds": 0,
            "sample_count": 6,
        },
        "garaza": {
            "avg_temp": 21.5,
            "is_ready": True,
            "is_stale": False,
            "age_seconds": 0,
            "sample_count": 6,
        },
    }
    
    relay_state = {
        "mode": "auto",
        "actual_state": "on",
        "desired_state": "on",
        "last_applied_at": 0,
        "manual_until": None,
    }
    
    relay_device = {
        "id": relay_id,
        "name": "heater",
        "pin": 17,
        "active_low": 0,
        "is_enabled": True,
    }
    
    def fake_db_list_relay_rules(_relay_id: str):
        return rules
    
    def fake_get_sensor_snapshot(sensor_name: str):
        return sensor_snapshots.get(sensor_name)
    
    def fake_db_get_relay_state_new(_relay_id: str):
        return relay_state
    
    def fake_db_get_relay_device(_relay_id: str):
        return relay_device
    
    def fake_db_update_relay_state_new(_relay_id: str, **kwargs):
        relay_state.update(kwargs)
    
    def fake_db_update_rule_last_triggered(rule_id: str):
        for rule in rules:
            if rule.get("id") == rule_id:
                rule["last_triggered_at"] = int(time.time())
                break
    
    def fake_db_log_relay_event(*_args, **_kwargs):
        return None
    
    def fake_apply_relay_hardware(_relay_id: str, _desired_state: str):
        return {"ok": True, "state": _desired_state}
    
    originals = {
        "db_list_relay_rules": smartify_app.db_list_relay_rules,
        "get_sensor_snapshot": smartify_app.get_sensor_snapshot,
        "db_get_relay_state_new": smartify_app.db_get_relay_state_new,
        "db_get_relay_device": smartify_app.db_get_relay_device,
        "db_update_relay_state_new": smartify_app.db_update_relay_state_new,
        "db_update_rule_last_triggered": smartify_app.db_update_rule_last_triggered,
        "db_log_relay_event": smartify_app.db_log_relay_event,
        "apply_relay_hardware": smartify_app.apply_relay_hardware,
    }
    
    try:
        smartify_app.db_list_relay_rules = fake_db_list_relay_rules
        smartify_app.get_sensor_snapshot = fake_get_sensor_snapshot
        smartify_app.db_get_relay_state_new = fake_db_get_relay_state_new
        smartify_app.db_get_relay_device = fake_db_get_relay_device
        smartify_app.db_update_relay_state_new = fake_db_update_relay_state_new
        smartify_app.db_update_rule_last_triggered = fake_db_update_rule_last_triggered
        smartify_app.db_log_relay_event = fake_db_log_relay_event
        smartify_app.apply_relay_hardware = fake_apply_relay_hardware
        
        smartify_app.reconcile_relay(relay_id, force=True)
        
        winner_rule = next((rule for rule in rules if rule["id"] == "rule-ugasi"), None)
        assert relay_state.get("actual_state") == "off", "Expected relay to turn OFF"
        assert winner_rule and winner_rule.get("last_triggered_at"), "Expected UGASI to update last_triggered_at"
        assert rules[0].get("last_triggered_at") is None, "Expected ON rule last_triggered_at to remain None"
        assert rules[1].get("last_triggered_at") is None, "Expected other OFF rule last_triggered_at to remain None"
        
        print("PASS: Winner is UGASI, relay OFF, last_triggered_at updated only for winner.")
        
        # Cooldown hold scenario: rule condition matches but cooldown blocks retrigger
        rules = [
            {
                "id": "rule-on-cooldown",
                "relay_id": relay_id,
                "name": "Heat On",
                "condition": {"type": "temperature", "sensor": "kombi", "operator": ">", "value": 5},
                "action": "turn_on",
                "priority": 50,
                "cooldown_seconds": 60,
                "is_enabled": True,
                "last_triggered_at": None,
                "created_at": 1,
            }
        ]
        sensor_snapshots = {
            "kombi": {
                "avg_temp": 21.3,
                "is_ready": True,
                "is_stale": False,
                "age_seconds": 0,
                "sample_count": 6,
            }
        }
        relay_state = {
            "mode": "auto",
            "actual_state": "off",
            "desired_state": "off",
            "last_applied_at": 0,
            "manual_until": None,
        }
        
        smartify_app.reconcile_relay(relay_id, force=True)
        first_trigger = rules[0].get("last_triggered_at")
        assert relay_state.get("actual_state") == "on", "Expected relay to turn ON"
        assert first_trigger, "Expected last_triggered_at to be set after first trigger"
        
        smartify_app.reconcile_relay(relay_id, force=True)
        second_trigger = rules[0].get("last_triggered_at")
        assert relay_state.get("actual_state") == "on", "Expected relay to stay ON during cooldown"
        assert second_trigger == first_trigger, "Expected last_triggered_at to remain unchanged during cooldown"
        
        print("PASS: Cooldown holds relay ON without no_match OFF flip.")
    finally:
        smartify_app.db_list_relay_rules = originals["db_list_relay_rules"]
        smartify_app.get_sensor_snapshot = originals["get_sensor_snapshot"]
        smartify_app.db_get_relay_state_new = originals["db_get_relay_state_new"]
        smartify_app.db_get_relay_device = originals["db_get_relay_device"]
        smartify_app.db_update_relay_state_new = originals["db_update_relay_state_new"]
        smartify_app.db_update_rule_last_triggered = originals["db_update_rule_last_triggered"]
        smartify_app.db_log_relay_event = originals["db_log_relay_event"]
        smartify_app.apply_relay_hardware = originals["apply_relay_hardware"]


if __name__ == "__main__":
    run_rule_engine_debug()

