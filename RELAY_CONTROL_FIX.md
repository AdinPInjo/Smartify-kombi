# Relay Control Fix - State Verification & Dual Schema Support

## Problem

Remote desired_state arrived and got acked, but heater relay did not actually switch.

**Log Evidence**:
```
New settings version 2 detected, applying...
Desired state: {'relays': {'heater': 'on'}}
Applying desired state...
Successfully applied and acknowledged version 2
Relay states after change: {'heater': 'off'}  ← WRONG!
```

### Root Causes

1. **Schema mismatch**: `apply_desired_state()` only supported `heater_force`/`heater_auto`, not the `relays.heater` format sent by dashboard
2. **No state verification**: `apply_heater_setting()` returned `True` without verifying hardware state
3. **ACK sent regardless**: ACK sent even when relay didn't actually switch

---

## Solution

### A) Dual Schema Support (Backward/Forward Compatible)

**Schema 1 - Direct relay control** (MANUAL override, highest priority):
```json
{
  "relays": {
    "heater": "on",
    "pump": "off"
  }
}
```
→ Treated as MANUAL override (`heater_force="on"`, `heater_auto=false`)  
→ Applies **IMMEDIATELY** (no hold-time)

**Schema 2 - Automation control** (legacy):
```json
{
  "heater_auto": true,
  "heater_on_below_c": 5.0,
  "heater_off_above_c": 23.0,
  "heater_force": "auto",
  "pump_force": "off"
}
```
→ AUTO mode with temperature thresholds  
→ Enforces 5-minute hold-time (prevents oscillation)

**Priority**:
1. `relays.heater` (MANUAL override) - immediate, no hold-time
2. `heater_force` "on"/"off" - immediate, no hold-time
3. `heater_auto` + thresholds - with hold-time

### B) State Verification After Relay Commands

**Before** (unreliable):
```python
def apply_heater_setting(enabled: bool) -> bool:
    state = "on" if enabled else "off"
    return set_relay_state("heater", state, mode="manual")  # Returns True even if failed
```

**After** (verified):
```python
def apply_heater_setting(enabled: bool, verify: bool = True) -> bool:
    state = "on" if enabled else "off"
    
    # Apply the setting
    if not set_relay_state("heater", state, mode="manual"):
        return False
    
    # Verify the state change (retry up to 5 times)
    for attempt in range(5):
        time.sleep(0.2)  # Wait for relay to switch
        relays = read_relay_states()
        if relays:
            heater_state = relays.get("heater", {}).get("state", "unknown")
            if heater_state == state:
                logger.debug(f"Heater state verified: {state}")
                return True
    
    logger.error(f"Failed to verify heater state change to {state}")
    return False
```

### C) ACK Only After Verified Success

**Before** (always ACKed):
```python
current_state = apply_desired_state(desired_state, state_manager)
# Always ack, even if relay didn't switch
if client.ack_state(remote_version, current_state):
    state_manager.save_applied_version(remote_version)
```

**After** (conditional ACK):
```python
current_state = apply_desired_state(desired_state, state_manager)

# Check if any critical actions FAILED
has_failures = any("FAILED" in action for action in actions)

if has_failures:
    logger.error("Settings application had FAILURES - NOT acknowledging")
    # Do NOT ack - will retry next cycle
else:
    # Acknowledge only if no failures
    if client.ack_state(remote_version, current_state):
        state_manager.save_applied_version(remote_version)
```

---

## Changes Made

### 1. `smartify/remote_sync/adapters.py`

**New function: `normalize_relay_value()`**:
- Accepts: `"on"/"off"` (case-insensitive), `True/False`, `1/0`
- Returns: `"on"`, `"off"`, or `None`

**Updated `apply_heater_setting()` and `apply_pump_setting()`**:
- Added `verify` parameter (default `True`)
- After applying, retries 5 times with 200ms delay
- Re-reads relay states to confirm change
- Returns `False` if state doesn't match
- Logs clear error if verification fails

**Enhanced `apply_desired_state()`**:
- **Step 1: Normalization** (top of function):
  ```python
  relays_cmd = desired_state.get("relays", {})
  if isinstance(relays_cmd, dict) and relays_cmd:
      # Map relays.heater to heater_force (MANUAL override)
      if "heater" in relays_cmd:
          heater_value = normalize_relay_value(relays_cmd["heater"])
          desired_state["heater_force"] = heater_value
          desired_state["heater_auto"] = False
          logger.info(f"Mapped relays.heater={relays_cmd['heater']} -> heater_force={heater_value}")
  ```

- **Step 2: Distinguish MANUAL vs AUTO**:
  - `is_manual_override = True` for `heater_force` "on"/"off"
  - `is_manual_override = False` for `heater_auto` + thresholds
  - MANUAL: no hold-time check
  - AUTO: enforce 5-minute hold-time

- **Step 3: Apply with verification**:
  ```python
  if apply_heater_setting(desired_heater_state, verify=True):
      actions_taken.append(f"heater {reason}")
  else:
      actions_taken.append(f"heater {reason} FAILED")
  ```

- **Step 4: Re-read relay states** (fresh verification):
  ```python
  current_state = build_current_state()  # Re-reads relays
  logger.info(f"Relay states after change (verified): {current_state['relays']}")
  ```

### 2. `smartify/remote_sync/runner.py`

**Settings loop checks for failures**:
```python
actions = current_state.get("actions_taken", [])
has_failures = any("FAILED" in action for action in actions)

if has_failures:
    logger.error("Settings application had FAILURES - NOT acknowledging")
    # Do NOT ack - will retry next cycle
else:
    # Acknowledge only if no failures
    if client.ack_state(remote_version, current_state):
        state_manager.save_applied_version(remote_version)
```

### 3. `smartify/remote_sync/tools/relay_smoke_test.py` (NEW)

Smoke test script for relay control without Supabase:
- Tests both schemas: `relays.heater` and `heater_force`
- Prints relay states before/after each command
- Validates control loop and state verification

**Usage**:
```bash
python3 smartify/remote_sync/tools/relay_smoke_test.py
```

---

## Behavior

### MANUAL Override (Immediate, No Hold-Time)

**Input**: `{"relays": {"heater": "on"}}`

**Logs**:
```
INFO - Detected relays override: {'heater': 'on'}
INFO - Mapped relays.heater=on -> heater_force=on, heater_auto=false
INFO - Applying MANUAL heater override (no hold-time): forced ON
DEBUG - Heater state verified: on
INFO - Actions: heater forced ON
INFO - Relay states after change (verified): {'heater': 'on'}
INFO - Successfully applied and acknowledged version X
```

### AUTO Mode (With Hold-Time)

**Input**: `{"heater_auto": true, "heater_on_below_c": 5.0, "heater_force": "auto"}`

**Logs** (if temp < 5°C):
```
INFO - Actions: heater auto ON (temp 4.5°C < 5.0°C)
INFO - Relay states after change (verified): {'heater': 'on'}
```

**Logs** (if changed recently):
```
INFO - Heater AUTO change blocked by hold time: 180s remaining
INFO - Actions: heater auto ON (temp 4.5°C < 5.0°C) (blocked: 180s hold time)
```

### Verification Failure

**Logs**:
```
ERROR - Failed to verify heater state change to on after 5 attempts
ERROR - Heater state change FAILED: desired=True, reason=forced ON
INFO - Actions: heater forced ON FAILED
ERROR - Settings application had FAILURES - NOT acknowledging version X
ERROR - Failed actions: ['heater forced ON FAILED']
```
→ Will retry on next cycle (15s later)

---

## Testing

### 1. Smoke Test (No Supabase)

```bash
# On Pi
cd /home/pi/Smartify-kombi
python3 smartify/remote_sync/tools/relay_smoke_test.py
```

**Expected output**:
```
RELAY SMOKE TEST
================================================================

INITIAL STATE
================================================================
  heater      : off    (auto mode)
  pump        : off    (manual mode)

TEST 1: Turn heater ON using relays schema
------------------------------------------------------------
Desired state: {'relays': {'heater': 'on'}}
Actions taken: ['heater forced ON']

STATE AFTER HEATER ON
================================================================
  heater      : on     (manual mode)
  pump        : off    (manual mode)

...
```

### 2. Integration Test (With Supabase)

**Update desired_state in Supabase**:
```sql
UPDATE device_settings
SET desired_state = '{"relays": {"heater": "on"}}'::jsonb
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Check Pi logs** (within 15 seconds):
```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected**:
```
INFO - New settings version X detected, applying...
INFO - Desired state: {'relays': {'heater': 'on'}}
INFO - Detected relays override: {'heater': 'on'}
INFO - Mapped relays.heater=on -> heater_force=on, heater_auto=false
INFO - Applying MANUAL heater override (no hold-time): forced ON
DEBUG - Heater state verified: on
INFO - Actions: heater forced ON
INFO - Relay states after change (verified): {'heater': 'on'}
INFO - Successfully applied and acknowledged version X
```

**Verify relay actually switched**:
```bash
curl -s http://127.0.0.1:8000/api/relays | jq '.relays[] | select(.name=="heater") | .state'
# Should output: "on"
```

---

## Acceptance Criteria

✅ **When desired_state is `{"relays":{"heater":"on"}}`, logs show**:
- ✅ Mapping detected: `"Detected relays override"`
- ✅ Normalization: `"Mapped relays.heater=on -> heater_force=on, heater_auto=false"`
- ✅ MANUAL override: `"Applying MANUAL heater override (no hold-time)"`
- ✅ Verification: `"Heater state verified: on"`
- ✅ Fresh state: `"Relay states after change (verified): {'heater': 'on'}"`
- ✅ ACK only after success: `"Successfully applied and acknowledged"`

✅ **Auto heater control still works**:
- ✅ `heater_auto=true` + `heater_force="auto"` uses thresholds
- ✅ Enforces 5-minute hold-time for AUTO decisions
- ✅ Prevents oscillation

✅ **Manual force overrides auto**:
- ✅ MANUAL applies immediately (no hold-time block)
- ✅ `relays.heater` or `heater_force` "on"/"off" bypass hold-time

✅ **Failures handled correctly**:
- ✅ If relay fails to switch: logs `FAILED`
- ✅ Does NOT ack failed settings
- ✅ Retries on next cycle

---

## Deployment

```bash
# Pull latest code
cd /home/pi/Smartify-kombi
git pull origin feature/remote-sync

# Restart service
sudo systemctl restart smartify-remote-sync

# Verify
tail -f /var/log/smartify/remote_sync.log
```

**Look for**:
- ✅ `"Detected relays override"` when using `relays` schema
- ✅ `"Heater state verified"` after relay commands
- ✅ `"Relay states after change (verified)"` with correct states
- ✅ No `FAILED` actions (unless relay API issue)

---

## Summary

✅ **Fixed**:
- Relay control now works with `{"relays": {"heater": "on"}}` schema
- State verification ensures relay actually switched
- ACK only sent after verified success
- Failures logged clearly and retried

✅ **Backward Compatible**:
- Legacy `heater_force`/`heater_auto` still works
- AUTO mode with hold-time preserved
- MANUAL override bypasses hold-time

✅ **Reliable**:
- 5 retry attempts with 200ms delay
- Fresh relay states after changes
- Clear FAILED logging
- No ACK if verification fails

**Relay control is now reliable and verifiable!** 🎉

