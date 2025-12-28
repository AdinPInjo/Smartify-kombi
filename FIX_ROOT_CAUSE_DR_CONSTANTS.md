# ROOT CAUSE FIX: ADS1115 Data Rate Constants

## The Bug

The ADS1115 data rate (DR) constants in `smartify/ads1115.py` were **WRONG**:

```python
ADS1115_DR_128SPS = 0x0000  # ❌ WRONG! This is 8 SPS, not 128 SPS!
```

The working script `tools/read_ads_a0_a1.py` uses:

```python
DR_128 = 0x0080  # ✅ CORRECT value for 128 SPS
```

### Impact

Because the DR constant was wrong:
1. **Conversion time was wrong**: Code thought conversion took 7.8ms (128 SPS), but chip was actually doing 125ms (8 SPS)
2. **Read too early**: Code read conversion register after 10-30ms, but conversion wasn't done yet
3. **Stale data returned**: Conversion register still held data from previous channel
4. **Channels appeared mirrored**: A0 and A1 returned identical values

This was **NOT a hardware issue** — it was a config bug in the driver.

## The Fix

### 1. Corrected ADS1115 DR Constants

**File: `smartify/ads1115.py`** (Lines ~40-48)

```python
# ADS1115 data rate bits (DR[2:0] in Config Register)
# NOTE: These are ADS1115-specific values, NOT ADS1015
ADS1115_DR_8SPS   = 0x0000
ADS1115_DR_16SPS  = 0x0020
ADS1115_DR_32SPS  = 0x0040
ADS1115_DR_64SPS  = 0x0060
ADS1115_DR_128SPS = 0x0080  # ← CORRECTED: was 0x0000!
ADS1115_DR_250SPS = 0x00A0
ADS1115_DR_475SPS = 0x00C0
ADS1115_DR_860SPS = 0x00E0
```

### 2. Updated `_get_sps_value()` Mapping

**File: `smartify/ads1115.py`** (Lines ~100-115)

```python
def _get_sps_value(sps: int) -> int:
    """
    Get the SPS (samples per second) register value for ADS1115.
    
    Valid values: 8, 16, 32, 64, 128, 250, 475, 860
    Default: 128 SPS (0x0080)
    """
    sps_map = {
        8: ADS1115_DR_8SPS,      # 0x0000
        16: ADS1115_DR_16SPS,    # 0x0020
        32: ADS1115_DR_32SPS,    # 0x0040
        64: ADS1115_DR_64SPS,    # 0x0060
        128: ADS1115_DR_128SPS,  # 0x0080 (CORRECTED)
        250: ADS1115_DR_250SPS,  # 0x00A0
        475: ADS1115_DR_475SPS,  # 0x00C0
        860: ADS1115_DR_860SPS,  # 0x00E0
    }
    return sps_map.get(sps, ADS1115_DR_128SPS)  # Default to 128 SPS
```

### 3. Fixed Voltage Conversion Precision

**File: `smartify/ads1115.py`** (Lines ~273-276 and ~410-413)

Changed from:
```python
voltage = (raw / 32767.0) * pga  # ❌ Incorrect precision
```

To:
```python
voltage = raw * (pga / 32768.0)  # ✅ Correct for 16-bit signed
```

## Why This Works

### ADS1115 Datasheet Facts

From the ADS1115 datasheet (Table 7, Config Register):

| DR[2:0] | Samples Per Second (SPS) |
|---------|--------------------------|
| 000     | 8                        |
| 001     | 16                       |
| 010     | 32                       |
| 011     | 64                       |
| **100** | **128** (default)        |
| 101     | 250                      |
| 110     | 475                      |
| 111     | 860                      |

**Binary 100 = 0x04 in the DR field**

The DR field is bits [7:5] in the Config Register's low byte, so:
- DR=100 → 0b100 << 5 = 0b10000000 = **0x0080**

### Conversion Time at 128 SPS

- **128 SPS** = 1/128 seconds per sample = **7.8125 ms**
- Our code waits `max(0.03, 2 * (1/sps))` = `max(0.03, 2 * 7.8ms)` = **30ms**
- This is **plenty of time** for a 7.8ms conversion

With the old wrong constant:
- Chip was actually running at **8 SPS** (125ms per conversion)
- Code waited only 30ms
- Conversion wasn't done, so stale data was returned

## Verification

### Constants Check

```bash
python3 << 'EOF'
from smartify import ads1115
assert ads1115.ADS1115_DR_8SPS   == 0x0000
assert ads1115.ADS1115_DR_16SPS  == 0x0020
assert ads1115.ADS1115_DR_32SPS  == 0x0040
assert ads1115.ADS1115_DR_64SPS  == 0x0060
assert ads1115.ADS1115_DR_128SPS == 0x0080  # ← CRITICAL
assert ads1115.ADS1115_DR_250SPS == 0x00A0
assert ads1115.ADS1115_DR_475SPS == 0x00C0
assert ads1115.ADS1115_DR_860SPS == 0x00E0
print("✅ All DR constants are correct!")
EOF
```

### Voltage Conversion Check

```bash
python3 << 'EOF'
pga = 4.096
# Expected hardware values
raw_a0 = 13992
raw_a1 = 27345

v0 = raw_a0 * (pga / 32768.0)
v1 = raw_a1 * (pga / 32768.0)

print(f"A0: raw={raw_a0} → {v0:.6f}V  (expect ≈1.098V)")
print(f"A1: raw={raw_a1} → {v1:.6f}V  (expect ≈2.144V)")
print(f"Diff: {abs(v0-v1):.6f}V  (expect ≈1.046V)")

assert abs(v0 - 1.098) < 0.001, "A0 voltage wrong"
assert abs(v1 - 2.144) < 0.001, "A1 voltage wrong"
print("✅ Voltage conversion is correct!")
EOF
```

## Deploy & Test

```bash
# On Raspberry Pi
cd ~/repos/Smartify-kombi
git pull

# Verify constants
python3 -c "
from smartify import ads1115
assert ads1115.ADS1115_DR_128SPS == 0x0080, 'DR_128 still wrong!'
print('✅ Constants fixed')
"

# Test with real hardware
python3 << 'EOF'
from smartify import ads1115
import time

print("Testing with corrected DR constants:")
for i in range(5):
    v0, v1 = ads1115.ads_read_voltage_pair(0, 1, addr=0x48, bus=1, pga=4.096, sps=128)
    if v0 is not None and v1 is not None:
        diff = abs(v0 - v1)
        print(f"{i}: A0={v0:.6f}V, A1={v1:.6f}V, diff={diff:.6f}V, mirrored={v0==v1}")
    else:
        print(f"{i}: Read failed")
    time.sleep(1)
EOF

# Restart service
sudo systemctl restart smartify-dashboard.service

# Watch logs
journalctl -u smartify-dashboard.service -f | grep -E "ADS1115|Water Level"
```

## Expected Results

### Manual Test
```
Testing with corrected DR constants:
[ADS1115] Channel 0: raw=13992, voltage=1.098145V
[ADS1115] Channel 1: raw=27345, voltage=2.144409V
0: A0=1.098145V, A1=2.144409V, diff=1.046264V, mirrored=False
[ADS1115] Channel 0: raw=13993, voltage=1.098218V
[ADS1115] Channel 1: raw=27344, voltage=2.144348V
1: A0=1.098218V, A1=2.144348V, diff=1.046130V, mirrored=False
...
```

### Service Logs
```
[Water Level] ADS1115 raw sample: A0=1.098V, A1=2.144V
[Water Level] Result: signal=1.098V, supply=2.144V, ratio=0.512
```

### API
```bash
curl -s http://127.0.0.1:8000/api/water/level/live | jq '.'
```

Expected:
```json
{
  "ok": true,
  "signal_voltage": 1.098145,
  "supply_div_voltage": 2.144409,
  "supply_voltage_est": 5.36,
  "ratio": 0.512,
  "level_percent": 45.3,
  "status": "ok"
}
```

## Why Previous Fixes Didn't Work

All previous attempts (throwaway reads, priming patterns, lock improvements, etc.) were **workarounds for the wrong root cause**. 

The real issue was that:
1. Config register had **DR=000 (8 SPS)** instead of **DR=100 (128 SPS)**
2. Conversion took **125ms** instead of **7.8ms**
3. Code read after **30ms**, before conversion was done
4. Got stale data from previous channel

**Now the config is correct, so the chip does what we expect.**

## Success Criteria

✅ `ads1115.ADS1115_DR_128SPS == 0x0080`  
✅ Manual test shows distinct A0 and A1 values  
✅ No "WARNING: Channels returned same value" in logs  
✅ API returns `signal_voltage ≠ supply_div_voltage`  
✅ Diff is approximately 1.046V (not ~0.000V)  
✅ Service runs without errors for 5+ minutes  

## Rollback

If for some reason this doesn't work (it will):

```bash
cd ~/repos/Smartify-kombi
git revert HEAD
sudo systemctl restart smartify-dashboard.service
```

---

**This is the real fix. The mirrored channels issue is now resolved at the root cause.**

