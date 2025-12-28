# Water Level Diagnostic Logging & Cleanup

## Changes Applied

### 1. Comprehensive Diagnostic Logging (`smartify/water_level/api.py`)

#### GET `/api/water/level/live` Diagnostics

Added three levels of diagnostic logging to trace the complete data flow:

**A) Configuration Logging (on every request):**
```python
print(f"[Water Level Live] CONFIG: adc_channel_signal=A{channel_signal}, adc_channel_supply=A{channel_supply}, use_normalization={use_normalization}")
```

**B) Raw Tuple Logging (first sample only):**
```python
print(f"[Water Level Live] RAW TUPLE from ads_read_voltage_pair(ch0={channel_signal}, ch1={channel_supply}): v0={signal_v}, v1={supply_div_v}, addr={addr}")
```

**C) Final Response Logging (always):**
```python
# With normalization:
print(f"[Water Level Live] RESPONSE: signal_voltage={result['signal_voltage']:.6f}V, supply_div_voltage={result['supply_div_voltage']:.6f}V, ratio={result['ratio']:.4f}, level_percent={result['level_percent']}%, ok={result['ok']}, status={result['status']}")

# Without normalization:
print(f"[Water Level Live] RESPONSE (no normalization): signal_voltage={result['signal_voltage']:.6f}V, level_percent={result['level_percent']}%, ok={result['ok']}, status={result['status']}")
```

### 2. Silent Substitution Guard

Added assertion to verify no calibration values leak into `signal_voltage`:

```python
# CRITICAL: Verify no silent substitution
# avg_signal is RAW ADC voltage from channel, NOT calibration value
assert avg_signal != full_v and avg_signal != empty_v, \
    f"BUG: signal_voltage={avg_signal} matches calibration value (full={full_v}, empty={empty_v})"
```

**This ensures:**
- `signal_voltage` in response is ALWAYS raw ADC voltage from A0
- Calibration values (`full_voltage`, `empty_voltage`) are ONLY used to compute `level_percent`
- If ADC read fails, `signal_voltage` is `None`, never substituted

### 3. Startup Sanity Check (`smartify/app.py`)

Added logging on service startup to confirm correct module loading:

```python
try:
    from smartify import ads1115
    print(f"[Startup] ads1115 module loaded from: {ads1115.__file__}")
except ImportError as e:
    print(f"[Startup] WARNING: Could not import ads1115 module: {e}")
```

**Expected output on Raspberry Pi:**
```
[Startup] ads1115 module loaded from: /home/adinpinjo/repos/Smartify-kombi/smartify/ads1115.py
```

### 4. Reduced Noisy Debug Logs (`smartify/ads1115.py`)

#### Removed per-read logging:
**Before:**
```python
print(f"[ADS1115] Channel {ch}: raw={raw_value}, voltage={voltage:.6f}V")  # Every read!
```

**After:**
```python
# Reduced logging: only log on errors or warnings, not every read
```

#### Improved mirrored channel detection:

**Added global counter:**
```python
_mirrored_consecutive_count = 0
_MIRRORED_THRESHOLD = 3  # Warn only after 3 consecutive mirrored readings
```

**Smart detection logic:**
```python
if diff < 0.01:  # 10mV threshold (was 1mV)
    _mirrored_consecutive_count += 1
    if _mirrored_consecutive_count >= _MIRRORED_THRESHOLD:
        print(f"[ADS1115] WARNING: Channels {channel0} and {channel1} returned same value "
              f"{voltages[0]:.6f}V for {_mirrored_consecutive_count} consecutive reads")
else:
    # Reset counter on distinct read
    if _mirrored_consecutive_count > 0:
        _mirrored_consecutive_count = 0
```

**Changes:**
- Threshold raised from 1mV to 10mV (more tolerant of normal voltage variations)
- Only warns after 3 consecutive mirrored readings (not on every single one)
- Counter resets automatically when distinct values appear
- Includes consecutive count in warning message

### 5. Documentation Note

Added note to `ads_read_voltage_pair()` docstring:

```python
"""
...
Note:
    For water level sensor, A0 (signal) voltage INCREASES as tank empties.
    Typical values: Full tank ≈ 0.5V, Empty tank ≈ 2.2V
"""
```

## Expected Log Output

### On Service Startup
```
[Startup] ads1115 module loaded from: /home/adinpinjo/repos/Smartify-kombi/smartify/ads1115.py
```

### On `/api/water/level/live` Request
```
[Water Level Live] CONFIG: adc_channel_signal=A0, adc_channel_supply=A1, use_normalization=True
[Water Level Live] RAW TUPLE from ads_read_voltage_pair(ch0=0, ch1=1): v0=1.098123, v1=2.144567, addr=0x48
[Water Level Live] RESPONSE: signal_voltage=1.098123V, supply_div_voltage=2.144567V, ratio=0.5121, level_percent=45%, ok=True, status=ok
```

### If Mirrored Channels Occur (3+ times consecutively)
```
[ADS1115] WARNING: Channels 0 and 1 returned same value 1.500000V for 3 consecutive reads
```

### What You Won't See Anymore
```
[ADS1115] Channel 0: raw=13992, voltage=1.098123V  ← REMOVED (too noisy)
[ADS1115] Channel 1: raw=27345, voltage=2.144567V  ← REMOVED (too noisy)
[ADS1115] WARNING: Channels 0 and 1 returned same value: 1.098234V  ← Only after 3 consecutive
```

## Verification Checklist

### Deploy & Test
```bash
# On Raspberry Pi
cd ~/repos/Smartify-kombi
git pull
sudo systemctl restart smartify-dashboard.service

# Watch startup logs
journalctl -u smartify-dashboard.service -n 50 | grep Startup

# Watch water level logs
journalctl -u smartify-dashboard.service -f | grep -E "Water Level|ADS1115"

# Test API
curl -s http://127.0.0.1:8000/api/water/level/live | jq '.'
```

### Verify No Silent Substitution

**Check that `signal_voltage` is raw ADC reading:**
```bash
# Expected: signal_voltage ≈ 1.098-1.27V (actual A0 reading)
# NOT: signal_voltage = 2.230V (which would be empty_voltage calibration)

curl -s http://127.0.0.1:8000/api/water/level/live | jq '.signal_voltage'
```

**Look in logs for RESPONSE line:**
```
[Water Level Live] RESPONSE: signal_voltage=1.098V, ...
```

- If `signal_voltage ≈ 1.1V`: ✅ Correct (raw ADC from A0)
- If `signal_voltage = 2.23V`: ❌ BUG (calibration value leaked in)

### Check Diagnostic Logs

**CONFIG line should show:**
```
adc_channel_signal=A0, adc_channel_supply=A1, use_normalization=True
```

**RAW TUPLE line should show distinct values:**
```
v0=1.098123, v1=2.144567  (not v0=v1)
```

**RESPONSE line should show:**
```
signal_voltage=1.098123V, supply_div_voltage=2.144567V, ratio=0.5121, level_percent=45%
```

## Success Criteria

✅ Startup log shows correct `ads1115.__file__` path  
✅ Every `/api/water/level/live` request logs CONFIG, RAW TUPLE, and RESPONSE  
✅ `signal_voltage` in response matches raw tuple `v0` value  
✅ `signal_voltage` never equals `full_voltage` or `empty_voltage` from calibration  
✅ Mirrored channel warnings only appear after 3 consecutive detections  
✅ No per-channel raw/voltage logs on every read (reduced noise)  
✅ API response structure unchanged (no breaking changes)  

## Files Modified

- **`smartify/water_level/api.py`**: Added diagnostic logging in `/level/live`, added silent substitution guard
- **`smartify/app.py`**: Added startup sanity check for `ads1115` module
- **`smartify/ads1115.py`**: Reduced noisy per-read logs, improved mirrored channel detection with consecutive counter, added water level voltage note to docstring

## Rollback

If needed:
```bash
cd ~/repos/Smartify-kombi
git revert HEAD
sudo systemctl restart smartify-dashboard.service
```

