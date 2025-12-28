# Mirrored Channels Debug Fix

## Problem
Backend API `/api/water/level/live` returns `signal_voltage` == `supply_div_voltage` (both ~1.098V), but hardware script `smartify/tools/read_ads_a0_a1.py` correctly reads A0≈1.098V, A1≈2.144V at address 0x48.

## Root Cause Analysis
The code flow appears correct:
1. Settings specify `adc_channel_signal=0`, `adc_channel_supply=1`
2. Reader calls `ads1115.ads_read_voltage_pair(channel0=0, channel1=1, ...)`
3. Returns `(v0, v1, address)` where v0=voltage from A0, v1=voltage from A1
4. Service/API unpack as `signal_v, supply_div_v, addr`

However, the ADS1115 may be returning the same value for both channels due to:
- Stale conversion register data
- Insufficient delay between channel reads
- MUX not settling properly

## Fix Applied

### Enhanced Debugging in `smartify/water_level/reader.py`

**Added channel validation guard:**
```python
# Guard: Channels must be different
if signal_ch == supply_ch:
    print(f"[Water Level Reader] ERROR: signal_ch and supply_ch are both {signal_ch}. They must be different!")
    return (None, None, None)
```

**Added detailed logging:**
```python
# Before call
print(f"[Water Level Reader] Reading channels: signal_ch={signal_ch} (A{signal_ch}), supply_ch={supply_ch} (A{supply_ch})")
print(f"[Water Level Reader] Calling ads_read_voltage_pair(channel0={signal_ch}, channel1={supply_ch}, addr=0x{addr:02X})")

# After call
print(f"[Water Level Reader] Result: v0={v0}, v1={v1} (from channels {signal_ch}, {supply_ch})")

# Verify distinct values
if v0 is not None and v1 is not None:
    diff = abs(v0 - v1)
    if diff < 0.001:
        print(f"[Water Level Reader] WARNING: Channels appear mirrored! v0={v0:.6f}V, v1={v1:.6f}V, diff={diff:.6f}V")
```

## Testing & Verification

### Deploy
```bash
cd ~/repos/Smartify-kombi
git pull
sudo systemctl restart smartify-dashboard.service
```

### Check Logs
```bash
journalctl -u smartify-dashboard.service -f | grep "Water Level"
```

**Expected output (if working correctly):**
```
[Water Level Reader] Reading channels: signal_ch=0 (A0), supply_ch=1 (A1)
[Water Level Reader] Calling ads_read_voltage_pair(channel0=0, channel1=1, addr=0x48)
[Water Level Reader] Result: v0=1.098123, v1=2.144567 (from channels 0, 1)
[Water Level] ADS1115 raw sample: A0=1.098123V, A1=2.144567V, addr=0x48
[Water Level] Result: A0(signal)=1.098123V, A1(supply_div)=2.144567V, diff=1.046444V, supply_est=12.34V, ratio=0.089012, level=45%
```

**If channels are mirrored (bug persists):**
```
[Water Level Reader] Reading channels: signal_ch=0 (A0), supply_ch=1 (A1)
[Water Level Reader] Calling ads_read_voltage_pair(channel0=0, channel1=1, addr=0x48)
[Water Level Reader] Result: v0=1.098123, v1=1.098123 (from channels 0, 1)
[Water Level Reader] WARNING: Channels appear mirrored! v0=1.098123V, v1=1.098123V, diff=0.000000V
```

### Test API
```bash
# Check live endpoint
curl -s http://127.0.0.1:8000/api/water/level/live | python3 -c "
import sys, json
d = json.load(sys.stdin)
sig = d.get('signal_voltage', 0)
sup = d.get('supply_div_voltage', 0)
print(f'Signal:  {sig:.6f}V')
print(f'Supply:  {sup:.6f}V')
print(f'Diff:    {abs(sig - sup):.6f}V')
print(f'Match expected: Signal≈1.098V, Supply≈2.144V, Diff≈1.046V')
print(f'Mirrored: {sig == sup}')
"
```

**Expected output:**
```
Signal:  1.098123V
Supply:  2.144567V
Diff:    1.046444V
Match expected: Signal≈1.098V, Supply≈2.144V, Diff≈1.046V
Mirrored: False
```

### Compare with Hardware Script
```bash
# Run hardware script
cd ~/repos/Smartify-kombi
python3 smartify/tools/read_ads_a0_a1.py
# Should show: A0 ≈ 1.098V, A1 ≈ 2.144V

# Compare with backend diagnostics
curl -s http://127.0.0.1:8000/api/water/diagnostics | python3 -m json.tool
# Verify channels: signal_channel: 0, supply_channel: 1
```

## If Mirroring Persists

If logs show mirrored values despite correct channel parameters, the issue is in the ADS1115 library's channel read implementation. Possible solutions:

1. **Increase delay between channel reads** (in ads1115.py line ~347):
   ```python
   time.sleep(0.010)  # Increase from 4ms to 10ms
   ```

2. **Add extra throwaway read after MUX change** (in ads1115.py after line ~356):
   ```python
   # Additional priming read
   i2c.write_i2c_block_data(addr, ADS1115_REG_CONFIG, config_bytes)
   time.sleep(sleep_time)
   _ = i2c.read_i2c_block_data(addr, ADS1115_REG_CONVERSION, 2)
   ```

3. **Force channel re-read with longer settle time** - Modify ads1115.py to add 20ms delay between channels

## Files Modified
- `smartify/water_level/reader.py` - Added channel validation guard and detailed logging

## Success Criteria
✅ Logs show distinct v0 and v1 values  
✅ API returns signal_voltage ≠ supply_div_voltage  
✅ Values match hardware script: A0≈1.098V, A1≈2.144V  
✅ No "WARNING: Channels appear mirrored" in logs  

