# Deploy ADS1115 Voltage Pair Fix

## What Changed

**File: `smartify/ads1115.py`**

### 1. New Helper Function: `_read_raw_with_smbus()`

Created a helper that performs the **exact same 6-step pattern** as `ads_read_raw_single_ended()`, but accepts an existing SMBus instance:

```python
def _read_raw_with_smbus(i2c, addr, channel, pga, sps):
    # Step 1: Write config (OS|MUX|PGA|MODE|DR|disable comparator)
    config_bytes = [(config >> 8) & 0xFF, config & 0xFF]  # Big-endian
    i2c.write_i2c_block_data(addr, REG_CONFIG, config_bytes)
    
    # Step 2: Wait 4ms for MUX to settle
    time.sleep(0.004)
    
    # Step 3: Throwaway read (clear stale data)
    try:
        _ = i2c.read_i2c_block_data(addr, REG_CONVERSION, 2)
    except:
        pass
    
    # Step 4: Write config again to re-trigger conversion
    i2c.write_i2c_block_data(addr, REG_CONFIG, config_bytes)
    
    # Step 5: Wait for conversion: max(0.03, 2*(1/sps))
    sleep_time = max(0.03, 2 * (1.0 / sps))
    time.sleep(sleep_time)
    
    # Step 6: Read final conversion value
    data = i2c.read_i2c_block_data(addr, REG_CONVERSION, 2)
    raw_value = (data[0] << 8) | data[1]
    if raw_value > 32767:
        raw_value -= 65536
    return raw_value
```

### 2. Refactored `ads_read_voltage_pair()`

Now calls `_read_raw_with_smbus()` for each channel within a single SMBus session and I2C_LOCK:

```python
def ads_read_voltage_pair(channel0, channel1, ...):
    for attempt in range(3):
        try:
            with I2C_LOCK:
                with SMBus(bus) as i2c:
                    # Channel 0: Use proven 6-step pattern
                    raw0 = _read_raw_with_smbus(i2c, addr, channel0, pga, sps)
                    voltage0 = (raw0 / 32767.0) * pga if raw0 else None
                    
                    # Channel 1: Use proven 6-step pattern
                    raw1 = _read_raw_with_smbus(i2c, addr, channel1, pga, sps)
                    voltage1 = (raw1 / 32767.0) * pga if raw1 else None
                    
                    return (voltage0, voltage1)
        except (OSError, IOError) as e:
            # Retry with backoff...
```

## Key Points

✅ **Same pattern as working code**: Uses the exact 6-step sequence from `ads_read_raw_single_ended()`  
✅ **Single SMBus session**: Both channels read in one `with SMBus(bus) as i2c:` context  
✅ **Serialized I2C access**: Entire pair read protected by `I2C_LOCK`  
✅ **Big-endian byte order**: Config bytes are `[(config >> 8) & 0xFF, config & 0xFF]`  
✅ **Same timing**: Uses `max(0.03, 2 * (1.0 / sps))` sleep formula (not the simplified 10ms)  
✅ **Retry logic**: 3 attempts with 50ms/100ms/150ms backoff on I/O errors  

## Deploy Commands

```bash
# 1. SSH to Raspberry Pi
ssh pi@raspberrypi.local

# 2. Navigate to repo
cd ~/repos/Smartify-kombi

# 3. Pull latest changes
git pull

# 4. Verify syntax
python3 -m py_compile smartify/ads1115.py
python3 -c "from smartify import ads1115; print('Import OK')"

# 5. Test manually (should show distinct values)
python3 << 'EOF'
from smartify import ads1115
import time

print("Testing ads_read_voltage_pair with 6-step pattern:")
for i in range(5):
    v0, v1 = ads1115.ads_read_voltage_pair(0, 1, addr=0x48, bus=1, pga=4.096, sps=128)
    if v0 is not None and v1 is not None:
        diff = abs(v0 - v1)
        mirrored = (v0 == v1)
        print(f"{i}: A0={v0:.6f}V, A1={v1:.6f}V, diff={diff:.6f}V, mirrored={mirrored}")
    else:
        print(f"{i}: Read failed - v0={v0}, v1={v1}")
    time.sleep(1)
EOF

# 6. Restart service
sudo systemctl restart smartify-dashboard.service

# 7. Watch logs
journalctl -u smartify-dashboard.service -f | grep -E "ADS1115|Water Level"
```

## Expected Output

### Manual Test
```
Testing ads_read_voltage_pair with 6-step pattern:
[ADS1115] Channel 0: raw=13992, voltage=1.098123V
[ADS1115] Channel 1: raw=27345, voltage=2.144567V
0: A0=1.098123V, A1=2.144567V, diff=1.046444V, mirrored=False
[ADS1115] Channel 0: raw=13994, voltage=1.098279V
[ADS1115] Channel 1: raw=27346, voltage=2.144598V
1: A0=1.098279V, A1=2.144598V, diff=1.046319V, mirrored=False
...
```

### Service Logs
```
[Water Level Reader] Reading channels: signal_ch=0 (A0), supply_ch=1 (A1)
[Water Level Reader] Calling ads_read_voltage_pair(channel0=0, channel1=1, addr=0x48)
[ADS1115] Channel 0: raw=13992, voltage=1.098123V
[ADS1115] Channel 1: raw=27345, voltage=2.144567V
[Water Level Reader] Result: v0=1.098123, v1=2.144567 (from channels 0, 1)
[Water Level] ADS1115 raw sample: A0=1.098V, A1=2.145V
```

### API Test
```bash
curl -s http://127.0.0.1:8000/api/water/level/live | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"Signal:  {d['signal_voltage']:.6f}V\")
print(f\"Supply:  {d['supply_div_voltage']:.6f}V\")
print(f\"Diff:    {abs(d['signal_voltage'] - d['supply_div_voltage']):.6f}V\")
print(f\"Mirrored: {d['signal_voltage'] == d['supply_div_voltage']}\")
"
```

**Expected:**
```
Signal:  1.098123V
Supply:  2.144567V
Diff:    1.046444V
Mirrored: False
```

## Success Criteria

✅ Manual test shows distinct A0 and A1 values  
✅ No "WARNING: Channels returned same value" in logs  
✅ API returns `signal_voltage` ≠ `supply_div_voltage`  
✅ Diff is approximately 1.046V (not ~0.000V)  
✅ Service runs without errors for 5+ minutes  

## Rollback

If the fix doesn't work:

```bash
cd ~/repos/Smartify-kombi
git log --oneline -5  # Find the commit before this change
git revert <commit_hash>
sudo systemctl restart smartify-dashboard.service
```

## Why This Should Work

1. **Proven pattern**: The 6-step sequence is already working perfectly in `ads_read_raw_single_ended()` and in the standalone CLI script `tools/read_ads_a0_a1.py`.

2. **MUX switching handled correctly**: Each channel gets:
   - Fresh config write with correct MUX bits
   - 4ms MUX settle time
   - Throwaway read to clear old conversion register
   - Fresh conversion trigger
   - Full conversion wait time
   - Final read of fresh data

3. **No shortcuts**: We removed the simplified single-shot approach that only did write→wait→read, which was susceptible to stale data.

4. **Single session**: Both channels are read in one SMBus connection, avoiding the overhead of opening/closing the bus between channels.

5. **Serialized access**: The entire pair read is atomic within `I2C_LOCK`, preventing any concurrent access that could cause MUX confusion.

## Performance

**Per channel (with 6-step pattern):**
- Step 1: Write config (~0.1ms)
- Step 2: Wait 4ms
- Step 3: Throwaway read (~0.1ms)
- Step 4: Write config (~0.1ms)
- Step 5: Wait 30ms (for 128 SPS)
- Step 6: Read conversion (~0.1ms)
- **Total: ~34ms per channel**

**Total for pair: ~68ms** (vs. ~20ms with simplified approach, but that approach was unreliable)

This is acceptable for a 60-second sampling interval.

