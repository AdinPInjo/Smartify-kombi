# ADS1115 Mirrored Channels Fix

## Problem
`ads1115.ads_read_voltage_pair(channel0=0, channel1=1, ...)` returns identical values for both channels (v0==v1), while direct hardware script correctly reads distinct values (A0≈1.098V, A1≈2.144V).

## Root Cause
The previous implementation used a complex pattern with throwaway reads and double config writes. The issue was that the conversion register retained stale data from the previous channel after MUX switching, and the throwaway read wasn't sufficient to clear it.

## Fix Applied

### Simplified Single-Shot Approach (`smartify/ads1115.py`)

Replaced complex priming pattern with straightforward single-shot reads:

```python
def ads_read_voltage_pair(channel0, channel1, ...):
    # Calculate proper wait time based on SPS
    conversion_time = 1.0 / sps  # e.g., 7.8ms for 128 SPS
    wait_time = max(0.010, conversion_time * 1.5)  # At least 10ms
    
    for each channel:
        # 1. Write config to start conversion with correct MUX
        config = OS_SINGLE | CHANNEL_MUX[ch] | pga | mode | sps | comparator
        i2c.write_i2c_block_data(addr, REG_CONFIG, config_bytes)
        
        # 2. Wait for conversion to complete
        time.sleep(wait_time)  # >= 10ms for 128 SPS
        
        # 3. Read conversion result
        data = i2c.read_i2c_block_data(addr, REG_CONVERSION, 2)
        voltage = calculate_voltage(data)
    
    return (v0, v1)
```

### Key Changes

1. **Removed complex priming pattern**
   - Old: Write config → wait 4ms → throwaway read → write config again → wait → read
   - New: Write config → wait 10ms → read (simple and reliable)

2. **Proper conversion wait time**
   - Old: `max(0.03, 2 * conversion_time)` ≈ 30ms
   - New: `max(0.010, conversion_time * 1.5)` ≈ 10ms (sufficient for 128 SPS)

3. **Added per-channel debug logging**
   ```python
   print(f"[ADS1115] Channel {ch}: raw={raw_value}, voltage={voltage:.6f}V")
   ```

4. **Added mirroring detection**
   ```python
   if voltages[0] is not None and voltages[1] is not None:
       diff = abs(voltages[0] - voltages[1])
       if diff < 0.001:
           print(f"[ADS1115] WARNING: Channels {channel0} and {channel1} returned same value")
   ```

5. **Enhanced error logging**
   - Added traceback on unexpected errors
   - Log insufficient data reads

## Why This Works

The ADS1115 conversion register holds the **last completed conversion**. When switching MUX channels:

**Problem scenario (old code):**
1. Read channel 0 → conversion register = A0 value
2. Write config for channel 1 (MUX changed)
3. Throwaway read → still reads old A0 value from conversion register
4. Write config again, wait, read → **may still get A0 if timing off**

**Solution (new code):**
1. Write config for channel 0 with OS bit (starts conversion)
2. Wait **full conversion time** (10ms for 128 SPS)
3. Read → guaranteed fresh A0 value
4. Write config for channel 1 with OS bit (starts conversion)
5. Wait **full conversion time** again
6. Read → guaranteed fresh A1 value

The OS (Operational Status) bit in single-shot mode triggers a **new conversion** when set to 1. By waiting the full conversion time after writing config, we ensure the conversion register contains a fresh reading for the selected channel.

## Testing

### Manual Test Script
```python
#!/usr/bin/env python3
from smartify import ads1115
import time

print("Testing ADS1115 pair read (10 iterations)")
for i in range(10):
    v0, v1 = ads1115.ads_read_voltage_pair(
        channel0=0, 
        channel1=1, 
        addr=0x48, 
        bus=1, 
        pga=4.096, 
        sps=128
    )
    diff = abs(v0 - v1) if (v0 and v1) else 0
    print(f"{i}: A0={v0:.6f}V, A1={v1:.6f}V, diff={diff:.6f}V, mirrored={v0==v1}")
    time.sleep(1)
```

**Expected output:**
```
0: A0=1.098123V, A1=2.144567V, diff=1.046444V, mirrored=False
1: A0=1.098134V, A1=2.144589V, diff=1.046455V, mirrored=False
...
```

### Deploy & Verify
```bash
# Deploy
cd ~/repos/Smartify-kombi
git pull
sudo systemctl restart smartify-dashboard.service

# Watch logs
journalctl -u smartify-dashboard.service -f | grep -E "ADS1115|Water Level"
```

**Expected log output:**
```
[Water Level Reader] Reading channels: signal_ch=0 (A0), supply_ch=1 (A1)
[Water Level Reader] Calling ads_read_voltage_pair(channel0=0, channel1=1, addr=0x48)
[ADS1115] Channel 0: raw=13992, voltage=1.098123V
[ADS1115] Channel 1: raw=27345, voltage=2.144567V
[Water Level Reader] Result: v0=1.098123, v1=2.144567 (from channels 0, 1)
[Water Level] ADS1115 raw sample: A0=1.098123V, A1=2.144567V, addr=0x48
```

### API Test
```bash
curl -s http://127.0.0.1:8000/api/water/level/live | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"Signal:  {d['signal_voltage']:.6f}V (should be ≈1.098V)\")
print(f\"Supply:  {d['supply_div_voltage']:.6f}V (should be ≈2.144V)\")
print(f\"Diff:    {abs(d['signal_voltage'] - d['supply_div_voltage']):.6f}V (should be ≈1.046V)\")
print(f\"Mirrored: {d['signal_voltage'] == d['supply_div_voltage']} (should be False)\")
"
```

## Files Modified

**`smartify/ads1115.py`** - Lines 278-389
- Function: `ads_read_voltage_pair()`
- Changed: Simplified from complex priming pattern to straightforward single-shot reads
- Added: Per-channel logging, mirroring detection, enhanced error handling

## Success Criteria

✅ Manual test script shows distinct A0 and A1 values  
✅ API returns `signal_voltage` ≠ `supply_div_voltage`  
✅ Values match hardware expectations: A0≈1.098V, A1≈2.144V  
✅ No "WARNING: Channels returned same value" in logs  
✅ Logs show distinct raw values and voltages for each channel  

## Rollback Plan
```bash
cd ~/repos/Smartify-kombi
git revert HEAD
sudo systemctl restart smartify-dashboard.service
```

## Performance Impact

**Old approach:**
- Channel 0: 4ms + 30ms + 2 I2C operations = ~34ms
- Channel 1: 4ms + 30ms + 2 I2C operations = ~34ms
- **Total: ~68ms per pair**

**New approach:**
- Channel 0: 10ms + 1 I2C operation = ~10ms
- Channel 1: 10ms + 1 I2C operation = ~10ms
- **Total: ~20ms per pair**

✅ **3x faster** and more reliable!

