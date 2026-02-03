import time

from smartify import app as smartify_app


def run_pending_state_tests() -> None:
    now = int(time.time())
    relay_id = "relay-test"
    
    relay_state = {
        "mode": "auto",
        "actual_state": "on",
        "desired_state": "on",
        "last_applied_at": now,
    }
    relay_device_enabled = {
        "id": relay_id,
        "name": "heater",
        "is_enabled": True,
    }
    relay_device_disabled = {
        "id": relay_id,
        "name": "ventilator",
        "is_enabled": False,
    }
    
    def fake_db_get_relay_state_new(_relay_id: str):
        return relay_state
    
    def fake_db_get_relay_device(_relay_id: str):
        return relay_device_enabled
    
    def fake_evaluate_rules(_relay_id: str, _temp_data=None, _current_state=None):
        return ("on", None, None, True, "no_match")
    
    originals = {
        "db_get_relay_state_new": smartify_app.db_get_relay_state_new,
        "db_get_relay_device": smartify_app.db_get_relay_device,
        "evaluate_rules": smartify_app.evaluate_rules,
    }
    
    try:
        smartify_app.db_get_relay_state_new = fake_db_get_relay_state_new
        smartify_app.db_get_relay_device = fake_db_get_relay_device
        smartify_app.evaluate_rules = fake_evaluate_rules
        
        pending = smartify_app._get_relay_pending_state(relay_id)
        assert pending["pending"] is False, "Expected pending=false when state==desired"
        
        smartify_app.db_get_relay_device = lambda _relay_id: relay_device_disabled
        pending = smartify_app._get_relay_pending_state(relay_id)
        assert pending["pending"] is False, "Expected pending=false when relay disabled"
        
        print("PASS: Pending state tests (desired==actual, disabled relay).")
    finally:
        smartify_app.db_get_relay_state_new = originals["db_get_relay_state_new"]
        smartify_app.db_get_relay_device = originals["db_get_relay_device"]
        smartify_app.evaluate_rules = originals["evaluate_rules"]


if __name__ == "__main__":
    run_pending_state_tests()

