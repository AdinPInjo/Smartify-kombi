#!/usr/bin/env python3
"""
Relay Smoke Test

Tests relay control without Supabase by directly calling apply_desired_state.
Validates the control loop and state verification.

Usage:
    python3 smartify/remote_sync/tools/relay_smoke_test.py
"""

import sys
import time
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from remote_sync.adapters import (
    read_relay_states,
    apply_desired_state,
)


def print_relay_states(label: str):
    """Print current relay states"""
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")
    relays = read_relay_states()
    if relays:
        for name, data in relays.items():
            state = data.get("state", "unknown")
            mode = data.get("mode", "unknown")
            print(f"  {name:12s}: {state:6s} ({mode} mode)")
    else:
        print("  No relay states available")
    print()


def test_relay_control():
    """Test relay control with different schemas"""
    
    print("\n" + "="*60)
    print("RELAY SMOKE TEST")
    print("="*60)
    print("\nThis test validates relay control without Supabase.")
    print("It tests both schema formats:")
    print("  1. relays: {heater: 'on'/'off'} (MANUAL override)")
    print("  2. heater_force: 'on'/'off' (legacy format)")
    print()
    
    # Test 1: Read initial state
    print_relay_states("INITIAL STATE")
    
    # Test 2: Turn heater ON using relays schema (MANUAL override)
    print("TEST 1: Turn heater ON using relays schema")
    print("-" * 60)
    print("Desired state: {'relays': {'heater': 'on'}}")
    result = apply_desired_state({"relays": {"heater": "on"}})
    actions = result.get("actions_taken", [])
    print(f"Actions taken: {actions}")
    time.sleep(1)
    print_relay_states("STATE AFTER HEATER ON")
    
    # Test 3: Turn heater OFF using relays schema (MANUAL override)
    print("TEST 2: Turn heater OFF using relays schema")
    print("-" * 60)
    print("Desired state: {'relays': {'heater': 'off'}}")
    result = apply_desired_state({"relays": {"heater": "off"}})
    actions = result.get("actions_taken", [])
    print(f"Actions taken: {actions}")
    time.sleep(1)
    print_relay_states("STATE AFTER HEATER OFF")
    
    # Test 4: Turn heater ON using legacy heater_force schema
    print("TEST 3: Turn heater ON using heater_force (legacy)")
    print("-" * 60)
    print("Desired state: {'heater_force': 'on'}")
    result = apply_desired_state({"heater_force": "on"})
    actions = result.get("actions_taken", [])
    print(f"Actions taken: {actions}")
    time.sleep(1)
    print_relay_states("STATE AFTER HEATER_FORCE ON")
    
    # Test 5: Turn heater OFF using legacy heater_force schema
    print("TEST 4: Turn heater OFF using heater_force (legacy)")
    print("-" * 60)
    print("Desired state: {'heater_force': 'off'}")
    result = apply_desired_state({"heater_force": "off"})
    actions = result.get("actions_taken", [])
    print(f"Actions taken: {actions}")
    time.sleep(1)
    print_relay_states("STATE AFTER HEATER_FORCE OFF")
    
    # Test 6: Test pump control
    print("TEST 5: Turn pump ON using relays schema")
    print("-" * 60)
    print("Desired state: {'relays': {'pump': 'on'}}")
    result = apply_desired_state({"relays": {"pump": "on"}})
    actions = result.get("actions_taken", [])
    print(f"Actions taken: {actions}")
    time.sleep(1)
    print_relay_states("STATE AFTER PUMP ON")
    
    # Test 7: Turn pump OFF
    print("TEST 6: Turn pump OFF using relays schema")
    print("-" * 60)
    print("Desired state: {'relays': {'pump': 'off'}}")
    result = apply_desired_state({"relays": {"pump": "off"}})
    actions = result.get("actions_taken", [])
    print(f"Actions taken: {actions}")
    time.sleep(1)
    print_relay_states("STATE AFTER PUMP OFF")
    
    # Summary
    print("\n" + "="*60)
    print("SMOKE TEST COMPLETE")
    print("="*60)
    print("\nVerify that:")
    print("  ✓ Relay states changed as expected")
    print("  ✓ Actions logged correctly")
    print("  ✓ No FAILED actions (unless relay API unavailable)")
    print("  ✓ Both schema formats work (relays.heater and heater_force)")
    print()


if __name__ == "__main__":
    try:
        test_relay_control()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

