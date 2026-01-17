# Rule Engine Dictionary Conversion Fix

## Problem

The FastAPI/uvicorn backend was experiencing recurring `ValueError` crashes:

```
ValueError: dictionary update sequence element #0 has length 6; 2 is required
ValueError: dictionary update sequence element #0 has length 5; 2 is required
```

### Error Locations

Logs showed errors in three key areas:
1. `[Rule Engine] Error reconciling relay <uuid>: ...`
2. `[_get_relay_pending_state] Error for relay <uuid>: ...`
3. `[API] Error evaluating rule <uuid>: ...`

### Root Cause

The code was calling `dict(x)` or `dict.update(x)` where `x` was sometimes a **string** instead of a dict:
- `"heater"` → length 6 characters
- `"force"` → length 5 characters

Python's `dict()` constructor expects an iterable of `(key, value)` pairs. When given a string like `"heater"`, it tries to convert each character to a pair, causing:
```python
dict("heater")  # Tries: [('h',), ('e',), ('a',), ('t',), ('e',), ('r',)]
# ValueError: dictionary update sequence element #0 has length 1; 2 is required
```

This happened when:
- Rule data from DB was malformed (e.g., `condition` stored as string instead of JSON)
- API received invalid payloads
- Rule evaluation passed strings instead of dicts

## Solution

### 1. Created `coerce_to_dict()` Helper Function

Added a robust helper function that safely converts any value to a dict:

```python
def coerce_to_dict(value: Any, *, context: str = "") -> dict:
    """
    Normalize user/db JSON-ish values into a dict safely.
    Never raises ValueError from dict(value).
    
    Handles:
    - None → {}
    - dict → return as-is
    - str → try JSON parse, return {} if invalid
    - list of dicts → merge into one dict
    - list of (k,v) pairs → dict(pairs)
    - invalid types → log warning, return {}
    """
```

**Key Features:**
- ✅ Never crashes with `ValueError`
- ✅ Logs warnings with context when dropping invalid data
- ✅ Handles JSON strings, lists, tuples, and edge cases
- ✅ Returns empty dict `{}` on failure (safe default)

### 2. Applied Safety Checks in Critical Functions

#### A) `api_relay_rules_list()` (lines ~3180-3230)

**Before:**
```python
for rule in rules:
    rule_with_status = dict(rule)  # ❌ CRASH if rule is string
```

**After:**
```python
for rule in rules:
    rule_dict = coerce_to_dict(rule, context="api_relay_rules_list.rule")
    if not rule_dict:
        continue  # Skip invalid rules
    rule_with_status = dict(rule_dict)  # ✅ Safe
```

#### B) `evaluate_single_rule()` (line ~1943)

**Before:**
```python
def evaluate_single_rule(rule: Dict[str, Any], relay_id: str):
    if not rule.get("is_enabled", True):  # ❌ CRASH if rule is string
```

**After:**
```python
def evaluate_single_rule(rule: Dict[str, Any], relay_id: str):
    # Safety: Ensure rule is a dict
    if not isinstance(rule, dict):
        rule = coerce_to_dict(rule, context="evaluate_single_rule.rule")
        if not rule:
            return {error response}  # ✅ Safe error response
```

#### C) `evaluate_rules()` (line ~2250)

**Before:**
```python
for rule in enabled_rules:
    condition = rule.get("condition", {})  # ❌ CRASH if rule is string
```

**After:**
```python
for rule in enabled_rules:
    if not isinstance(rule, dict):
        rule = coerce_to_dict(rule, context="evaluate_rules.rule")
        if not rule:
            continue  # ✅ Skip invalid rules
    
    condition = rule.get("condition", {})
    if not isinstance(condition, dict):
        condition = coerce_to_dict(condition, context="evaluate_rules.condition")
```

#### D) `reconcile_relay()` (line ~2395)

**Before:**
```python
if matched_rule is not None:
    condition = matched_rule.get("condition", {})  # ❌ CRASH if condition is string
```

**After:**
```python
if matched_rule is not None:
    condition = matched_rule.get("condition", {})
    if not isinstance(condition, dict):
        condition = coerce_to_dict(condition, context="reconcile_relay.matched_rule.condition")
```

#### E) `_get_relay_pending_state()` (line ~2755)

**Before:**
```python
for rule in enabled_rules:
    condition = rule.get("condition", {})  # ❌ CRASH if rule is string
```

**After:**
```python
for rule in enabled_rules:
    if not isinstance(rule, dict):
        rule = coerce_to_dict(rule, context="_get_relay_pending_state.rule")
        if not rule:
            continue  # ✅ Skip invalid rules
    
    condition = rule.get("condition", {})
    if not isinstance(condition, dict):
        condition = coerce_to_dict(condition, context="_get_relay_pending_state.condition")
```

## Files Changed

- **`smartify/app.py`**:
  - Added `coerce_to_dict()` helper function (lines ~36-105)
  - Fixed `evaluate_single_rule()` (added safety check at start)
  - Fixed `evaluate_rules()` (added rule and condition safety checks)
  - Fixed `reconcile_relay()` (added condition safety check)
  - Fixed `_get_relay_pending_state()` (added rule and condition safety checks)
  - Fixed `api_relay_rules_list()` (replaced unsafe `dict(rule)` calls)

## Diagnostic Logging

When invalid data is encountered, the helper logs warnings with context:

```
[coerce_to_dict] Invalid dict-like payload for api_relay_rules_list.rule: got type=str value='heater' (not valid JSON, dropping)
[coerce_to_dict] Invalid dict-like payload for evaluate_rules.condition: got type=list with non-dict items (sample=['force', 'on'], dropping)
```

This helps identify where bad data is coming from without crashing the service.

## Backward Compatibility

✅ **No breaking changes**:
- If invalid payload comes in, it's treated as empty dict `{}`
- Rule evaluation skips invalid rules gracefully
- API endpoints return valid JSON error responses instead of crashing
- Rule engine continues processing other relays even if one fails

## Testing

### Manual Test Cases

1. **Valid rule (normal case)**:
   ```python
   rule = {"id": "123", "condition": {"type": "temperature", "sensor": "water"}}
   # ✅ Works as before
   ```

2. **Rule as string (edge case)**:
   ```python
   rule = "heater"
   # ✅ Logs warning, returns safe error response, doesn't crash
   ```

3. **Condition as string (edge case)**:
   ```python
   rule = {"id": "123", "condition": "force"}
   # ✅ Logs warning, treats condition as {}, doesn't crash
   ```

4. **Condition as list of strings (edge case)**:
   ```python
   rule = {"id": "123", "condition": ["heater", "on"]}
   # ✅ Logs warning, treats condition as {}, doesn't crash
   ```

### Verification Commands

After deployment, monitor logs for:

```bash
# Check for ValueError crashes (should be ZERO)
tail -f /var/log/smartify/app.log | grep "ValueError: dictionary update sequence"

# Check for coerce_to_dict warnings (indicates bad data sources)
tail -f /var/log/smartify/app.log | grep "\[coerce_to_dict\]"

# Check rule engine is running without crashes
tail -f /var/log/smartify/app.log | grep "\[Rule Engine\]"
```

## Expected Behavior

### Before Fix
```
[Rule Engine] Error reconciling relay abc-123: ValueError: dictionary update sequence element #0 has length 6; 2 is required
[API] Error evaluating rule xyz-456: ValueError: dictionary update sequence element #0 has length 5; 2 is required
```
**Result**: Service crashes, relay automation stops

### After Fix
```
[coerce_to_dict] Invalid dict-like payload for evaluate_rules.rule: got type=str value='heater' (not valid JSON, dropping)
[Rule Engine] Skipping invalid rule (not a dict): str
```
**Result**: Service continues, invalid rules skipped gracefully

## Benefits

✅ **No more crashes**: Service stays running even with bad data  
✅ **Clear diagnostics**: Logs show exactly where bad data comes from  
✅ **Graceful degradation**: Invalid rules skipped, valid rules continue  
✅ **Backward compatible**: Existing valid rules work exactly as before  
✅ **Production ready**: Safe for deployment without breaking changes

## Deployment

```bash
# On Raspberry Pi
cd /home/pi/Smartify-kombi
git pull origin feature/remote-sync
sudo systemctl restart smartify-api
```

Monitor logs for 5-10 minutes to verify no `ValueError` crashes occur.

