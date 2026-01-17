# Rule Validation Fix - Prevent Invalid Rules at Source

## Problem Identified

The previous fix (`coerce_to_dict()`) prevented crashes when **reading** invalid rules, but didn't prevent invalid rules from being **written** to the database in the first place.

### Root Cause

The API endpoints for creating and updating rules accepted `condition` payloads **without validation**:

```python
# api_relay_rule_create() - BEFORE
condition = body.get("condition", {})  # ❌ No validation!
db_create_relay_rule(relay_id, name, condition, ...)  # Stores any type

# api_rule_update() - BEFORE
condition = body.get("condition")  # ❌ No validation!
db_update_relay_rule(rule_id, name, condition, ...)  # Stores any type
```

If a client sent:
```json
{
  "name": "Bad Rule",
  "condition": "heater",  // ❌ String instead of dict!
  "action": "turn_on"
}
```

The string `"heater"` would be stored in `relay_rules.condition_json` as `"\"heater\""`, causing crashes when the rule engine tried to parse it.

---

## Solution

### 1. Added `validate_rule_condition()` Function

Created a comprehensive validation function (lines ~171-229):

```python
def validate_rule_condition(condition: Any) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Validate a rule condition payload.
    
    Returns:
        (is_valid, error_message, normalized_condition)
    
    Rules:
    - condition must be a dict (not string, list, etc.)
    - condition must have "type" field
    - For "temperature" type: must have "sensor", "operator", "value"
    - operator must be one of: "<", ">", "<=", ">="
    - value must be a number
    """
```

**Validation Rules:**

#### Type Check
- `condition` must be a **dict**, not string/list/number/etc.
- Rejects: `"heater"`, `["sensor", "value"]`, `123`, `null`

#### Required Fields
- Must have `"type"` field
- Rejects: `{}`

#### Temperature Type Validation
- Must have `"sensor"` (string)
- Must have `"operator"` (one of: `<`, `>`, `<=`, `>=`)
- Must have `"value"` (number)
- Rejects: `{"type": "temperature"}` (missing fields)
- Rejects: `{"type": "temperature", "operator": "==", ...}` (invalid operator)
- Rejects: `{"type": "temperature", "value": "hot", ...}` (non-numeric value)

#### Normalization
Valid conditions are normalized to ensure consistent types:
```python
{
  "type": "temperature",
  "sensor": "water",      // str
  "operator": "<",        // str
  "value": 5.0            // float
}
```

### 2. Updated API Endpoints with Validation

#### A) `api_relay_rule_create()` (POST `/api/relays/{relay_id}/rules`)

**Before:**
```python
condition = body.get("condition", {})
# No validation - accepts anything!
```

**After:**
```python
# Validate condition (must be a dict with proper structure)
condition_raw = body.get("condition", {})
is_valid, error_msg, condition = validate_rule_condition(condition_raw)
if not is_valid:
    return JSONResponse({
        "ok": False,
        "error": "invalid_condition",
        "message": error_msg,
        "received_type": type(condition_raw).__name__
    }, status_code=400)
```

#### B) `api_rule_update()` (PUT `/api/rules/{rule_id}`)

**Before:**
```python
condition = body.get("condition")
# No validation - accepts anything!
```

**After:**
```python
# Validate condition if provided (must be a dict with proper structure)
condition_raw = body.get("condition")
condition = None
if condition_raw is not None:
    is_valid, error_msg, condition = validate_rule_condition(condition_raw)
    if not is_valid:
        return JSONResponse({
            "ok": False,
            "error": "invalid_condition",
            "message": error_msg,
            "received_type": type(condition_raw).__name__
        }, status_code=400)
```

### 3. Created DB Cleanup Migration Script

Created `smartify/migrate_cleanup_invalid_rules.py` to clean up existing bad data:

**Features:**
- ✅ Scans all rules in the database
- ✅ Validates each `condition_json` field
- ✅ **Disables** invalid rules (doesn't delete)
- ✅ Provides detailed report of issues
- ✅ Supports dry-run mode (preview without changes)
- ✅ Idempotent (safe to run multiple times)

**Usage:**
```bash
# Preview what would be cleaned (no changes)
python3 smartify/migrate_cleanup_invalid_rules.py --dry-run

# Clean up invalid rules (disables them)
python3 smartify/migrate_cleanup_invalid_rules.py
```

**Output Example:**
```
🔧 Relay Rules Cleanup Migration
============================================================

📊 Scanning 5 rules...

❌ Invalid Rule: Heater Control (id=abc123...)
   Relay ID: xyz-relay-id
   Currently enabled: True
   Reason: condition is str, not dict
   condition_json: "heater"
   ✓ Disabled rule

============================================================
SUMMARY
============================================================
Total rules scanned: 5
Valid rules: 4
Invalid rules found: 1
Rules disabled: 1

⚠️  ACTION REQUIRED:
   - Review the invalid rules listed above
   - Fix or delete them via the admin UI
   - Invalid rules have been DISABLED (not deleted)
```

---

## API Error Responses

### Invalid Condition Type

**Request:**
```bash
curl -X POST http://localhost:8000/api/relays/abc-123/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Bad Rule",
    "condition": "heater",
    "action": "turn_on"
  }'
```

**Response:**
```json
{
  "ok": false,
  "error": "invalid_condition",
  "message": "condition must be a dict, got str",
  "received_type": "str"
}
```
**Status Code:** `400 Bad Request`

### Missing Required Field

**Request:**
```bash
curl -X POST http://localhost:8000/api/relays/abc-123/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Incomplete Rule",
    "condition": {"type": "temperature"},
    "action": "turn_on"
  }'
```

**Response:**
```json
{
  "ok": false,
  "error": "invalid_condition",
  "message": "temperature condition missing required field: sensor",
  "received_type": "dict"
}
```
**Status Code:** `400 Bad Request`

### Invalid Operator

**Request:**
```bash
curl -X POST http://localhost:8000/api/relays/abc-123/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Bad Operator",
    "condition": {
      "type": "temperature",
      "sensor": "water",
      "operator": "==",
      "value": 20
    },
    "action": "turn_on"
  }'
```

**Response:**
```json
{
  "ok": false,
  "error": "invalid_condition",
  "message": "invalid operator '==', must be one of: <, >, <=, >=",
  "received_type": "dict"
}
```
**Status Code:** `400 Bad Request`

### Valid Request

**Request:**
```bash
curl -X POST http://localhost:8000/api/relays/abc-123/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Valid Rule",
    "condition": {
      "type": "temperature",
      "sensor": "water",
      "operator": "<",
      "value": 5
    },
    "action": "turn_on",
    "priority": 100,
    "cooldown_seconds": 60
  }'
```

**Response:**
```json
{
  "ok": true,
  "rule": {
    "id": "...",
    "name": "Valid Rule",
    "condition": {
      "type": "temperature",
      "sensor": "water",
      "operator": "<",
      "value": 5.0
    },
    "action": "turn_on",
    ...
  }
}
```
**Status Code:** `201 Created`

---

## Files Changed

### `smartify/app.py`
1. **Added `validate_rule_condition()` function** (lines ~171-229)
   - Validates condition structure
   - Normalizes valid conditions
   - Returns clear error messages

2. **Updated `api_relay_rule_create()`** (lines ~3370-3385)
   - Validates `condition` before storing
   - Returns 400 error with details if invalid

3. **Updated `api_rule_update()`** (lines ~3410-3430)
   - Validates `condition` before updating
   - Returns 400 error with details if invalid

### `smartify/migrate_cleanup_invalid_rules.py` (NEW)
- Standalone migration script
- Scans and disables invalid rules
- Provides detailed reports
- Supports dry-run mode

### `RULE_VALIDATION_FIX.md` (NEW)
- Complete documentation
- API examples
- Migration guide

---

## Deployment & Testing

### 1. Deploy Code Changes

```bash
cd /home/pi/Smartify-kombi
git pull origin feature/remote-sync
sudo systemctl restart smartify-api
```

### 2. Run Migration Script

```bash
# Preview what would be cleaned (recommended first)
cd /home/pi/Smartify-kombi
python3 smartify/migrate_cleanup_invalid_rules.py --dry-run

# Clean up invalid rules
python3 smartify/migrate_cleanup_invalid_rules.py
```

### 3. Test Validation

```bash
# Test 1: Try to create rule with string condition (should be rejected)
curl -X POST http://localhost:8000/api/relays/YOUR-RELAY-ID/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Invalid",
    "condition": "heater",
    "action": "turn_on"
  }'

# Expected: 400 error with "condition must be a dict"

# Test 2: Try to create rule with valid condition (should succeed)
curl -X POST http://localhost:8000/api/relays/YOUR-RELAY-ID/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Valid",
    "condition": {
      "type": "temperature",
      "sensor": "water",
      "operator": "<",
      "value": 5
    },
    "action": "turn_on"
  }'

# Expected: 201 success with rule created
```

### 4. Verify No More Invalid Rules Created

```bash
# Monitor API logs for validation rejections
tail -f /var/log/smartify/app.log | grep "invalid_condition"

# Check database for any new invalid rules (should be zero)
sqlite3 /home/pi/Smartify-kombi/smartify/data/smartify.db \
  "SELECT id, name, condition_json FROM relay_rules WHERE condition_json NOT LIKE '{%';"
```

---

## Benefits

### Prevention (Validation at API)
✅ **Rejects invalid data at source** - can't create bad rules  
✅ **Clear error messages** - tells client exactly what's wrong  
✅ **Type safety** - ensures condition is always a dict  
✅ **Schema enforcement** - validates required fields and types

### Recovery (Coercion at Runtime)
✅ **No crashes** - existing bad data handled gracefully (from previous fix)  
✅ **Clear diagnostics** - logs show where bad data came from  
✅ **Graceful degradation** - invalid rules skipped, valid rules work

### Cleanup (Migration Script)
✅ **Finds all bad data** - comprehensive database scan  
✅ **Safe cleanup** - disables invalid rules (doesn't delete)  
✅ **Detailed reporting** - shows exactly what's wrong  
✅ **Dry-run mode** - preview before making changes

---

## Defense in Depth

This fix implements **three layers of protection**:

1. **Layer 1: Input Validation** (API endpoints)
   - Prevents invalid data from entering the system
   - Returns clear error messages to clients

2. **Layer 2: Runtime Safety** (coerce_to_dict)
   - Handles any existing bad data gracefully
   - Prevents crashes from legacy/corrupted data

3. **Layer 3: Data Cleanup** (migration script)
   - Identifies and disables existing invalid rules
   - Provides clear audit trail

**Result**: System is now robust at all levels - prevention, recovery, and cleanup.

---

## Testing Checklist

- [x] `validate_rule_condition()` rejects strings
- [x] `validate_rule_condition()` rejects lists
- [x] `validate_rule_condition()` rejects dicts without "type"
- [x] `validate_rule_condition()` rejects temperature without sensor/operator/value
- [x] `validate_rule_condition()` rejects invalid operators
- [x] `validate_rule_condition()` rejects non-numeric values
- [x] `validate_rule_condition()` accepts valid temperature conditions
- [x] `api_relay_rule_create()` returns 400 for invalid condition
- [x] `api_relay_rule_create()` creates rule for valid condition
- [x] `api_rule_update()` returns 400 for invalid condition
- [x] `api_rule_update()` updates rule for valid condition
- [x] Migration script finds invalid rules
- [x] Migration script disables invalid rules
- [x] Migration script dry-run mode works
- [x] No linter errors in modified code

