# Silent Substitution Guard Fix

## Problem

The previous "silent substitution guard" used an assertion:

```python
assert avg_signal != full_v and avg_signal != empty_v, \
    f"BUG: signal_voltage={avg_signal} matches calibration value"
```

**This was WRONG** because:
- When tank is actually **FULL**, `signal_voltage ≈ 0.497V` (matches `full_voltage`)
- When tank is actually **EMPTY**, `signal_voltage ≈ 2.230V` (matches `empty_voltage`)
- The assertion would falsely fail in these legitimate cases!

## Fix Applied

### 1. Removed Invalid Assertion

Deleted the assertion entirely from `smartify/water_level/api.py`.

### 2. Added Non-Fatal Diagnostic Logging

Replaced with informational logging that does NOT affect API behavior:

```python
# DIAGNOSTIC: Non-fatal check if signal is near calibration endpoints
# (This is EXPECTED when tank is actually full or empty)
if abs(avg_signal - full_v) < 0.02:
    print(f"[Water Level Live] INFO: Signal voltage {avg_signal:.6f}V is near FULL calibration {full_v:.6f}V (expected when tank is full)")
if abs(avg_signal - empty_v) < 0.02:
    print(f"[Water Level Live] INFO: Signal voltage {avg_signal:.6f}V is near EMPTY calibration {empty_v:.6f}V (expected when tank is empty)")
```

**Key points:**
- Threshold: 0.02V (20mV) - reasonable tolerance
- Informational only - does NOT change `ok`, `status`, or any response fields
- Helps verify signal voltage is from ADC, not substituted
- Expected to log when tank is legitimately full or empty

### 3. Enhanced Startup Logging

Improved `smartify/app.py` to ensure the startup log always appears:

```python
try:
    from smartify import ads1115
    print(f"[Startup] ADS1115 module loaded from: {ads1115.__file__}")
except ImportError as e:
    print(f"[Startup] WARNING: Could not import ads1115 module: {e}")
except Exception as e:
    print(f"[Startup] ERROR loading ads1115 module: {e}")
```

Added broader exception handling to ensure log always appears (even if import fails).

### 4. Preserved Existing Diagnostics

Kept all existing useful logging:
- ✅ CONFIG: channel assignment
- ✅ RAW TUPLE: raw ADC values
- ✅ RESPONSE: final API response

## Expected Behavior

### When Tank is Full (≈99-100%)
```
[Water Level Live] CONFIG: adc_channel_signal=A0, adc_channel_supply=A1, use_normalization=True
[Water Level Live] RAW TUPLE from ads_read_voltage_pair(ch0=0, ch1=1): v0=0.4975, v1=2.144, addr=0x48
[Water Level Live] INFO: Signal voltage 0.497500V is near FULL calibration 0.497000V (expected when tank is full)
[Water Level Live] RESPONSE: signal_voltage=0.497500V, supply_div_voltage=2.144000V, ratio=0.2319, level_percent=99%, ok=True, status=ok
```

### When Tank is Empty (≈0-1%)
```
[Water Level Live] CONFIG: adc_channel_signal=A0, adc_channel_supply=A1, use_normalization=True
[Water Level Live] RAW TUPLE from ads_read_voltage_pair(ch0=0, ch1=1): v0=2.2305, v1=2.144, addr=0x48
[Water Level Live] INFO: Signal voltage 2.230500V is near EMPTY calibration 2.230000V (expected when tank is empty)
[Water Level Live] RESPONSE: signal_voltage=2.230500V, supply_div_voltage=2.144000V, ratio=1.0402, level_percent=1%, ok=True, status=ok
```

### When Tank is Mid-Level (≈50%)
```
[Water Level Live] CONFIG: adc_channel_signal=A0, adc_channel_supply=A1, use_normalization=True
[Water Level Live] RAW TUPLE from ads_read_voltage_pair(ch0=0, ch1=1): v0=1.363, v1=2.144, addr=0x48
[Water Level Live] RESPONSE: signal_voltage=1.363000V, supply_div_voltage=2.144000V, ratio=0.6355, level_percent=50%, ok=True, status=ok
```
*(No INFO log because signal is not near calibration endpoints)*

### On Service Startup
```
[Startup] ADS1115 module loaded from: /home/adinpinjo/repos/Smartify-kombi/smartify/ads1115.py
```

## What Changed

### `smartify/water_level/api.py`
- ❌ Removed: `assert avg_signal != full_v and avg_signal != empty_v`
- ✅ Added: Non-fatal INFO logging when signal is near calibration values
- ✅ No change to API response schema or behavior

### `smartify/app.py`
- ✅ Enhanced: Broader exception handling for startup log
- ✅ Ensures: Startup log always appears in service logs

## Verification

```bash
# On Raspberry Pi
cd ~/repos/Smartify-kombi
git pull
sudo systemctl restart smartify-dashboard.service

# Check startup log
journalctl -u smartify-dashboard.service -n 100 | grep "Startup.*ADS1115"

# Test with full tank (should see INFO log)
curl -s http://127.0.0.1:8000/api/water/level/live | jq '{signal_voltage, level_percent, ok}'

# Watch logs
journalctl -u smartify-dashboard.service -f | grep "Water Level"
```

### Success Criteria

✅ Service starts without assertion errors  
✅ When tank is full (signal ≈ 0.497V), INFO log appears but API returns ok=true  
✅ When tank is empty (signal ≈ 2.230V), INFO log appears but API returns ok=true  
✅ When tank is mid-level, no INFO log (normal operation)  
✅ Startup log shows ADS1115 module path  
✅ All CONFIG/RAW TUPLE/RESPONSE logs still appear  

## Files Modified

- ✅ `smartify/water_level/api.py` - Removed assertion, added non-fatal diagnostics
- ✅ `smartify/app.py` - Enhanced startup logging with broader exception handling

## Rollback

If needed:
```bash
cd ~/repos/Smartify-kombi
git revert HEAD
sudo systemctl restart smartify-dashboard.service
```

---

**This fix ensures the diagnostic logging is informational only and does not interfere with legitimate full/empty tank readings.**

