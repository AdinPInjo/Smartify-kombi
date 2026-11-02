# ADS1115 Integration Setup

This document describes how to set up ADS1115 ADC reading on Raspberry Pi for Smartify.

## Hardware Setup

- ADS1115 connected to I2C bus 1 (default)
- I2C address: 0x48 (default, can be changed via A0 pin)

## Software Setup

### 1. Install smbus2 (already in requirements.txt)

```bash
pip install smbus2
```

### 2. Enable I2C on Raspberry Pi

```bash
sudo raspi-config
# Navigate to: Interface Options → I2C → Enable
```

### 3. Verify I2C Connection

```bash
# Check if ADS1115 is detected
i2cdetect -y 1
# Should show 0x48 if ADS1115 is connected
```

### 4. Set Up I2C Permissions (Non-Root Access)

The Smartify service runs as user `adinpinjo` (or your configured user). To allow non-root access to I2C:

```bash
# Add user to i2c group
sudo usermod -a -G i2c adinpinjo

# Verify user is in i2c group
groups

# Check /dev/i2c-1 permissions (should be rw-rw---- and group i2c)
ls -l /dev/i2c-1
# Output should show: crw-rw---- 1 root i2c 189, 1 ...

# If permissions are wrong, fix them (requires root):
sudo chmod 666 /dev/i2c-1  # Temporary fix
# OR use udev rules for permanent fix:
echo 'KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0664"' | sudo tee /etc/udev/rules.d/99-i2c-permissions.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

**Important**: After adding user to i2c group, log out and log back in (or restart) for group membership to take effect.

### 5. Test ADS1115 Reading

```bash
# Run test script (should work without sudo)
python tools/test_ads_smbus2.py

# Expected output:
# Testing ADS1115 on I2C bus 1, address 0x48...
# 1. Detecting ADS1115...
#    ✓ ADS1115 found at address 0x48
# 2. Reading voltages from all channels (A0-A3)...
#    Channel | Voltage (V)
#    ------- | -----------
#    A0     |   1.2345 V
#    A1     |   2.3456 V
#    A2     |   3.4567 V
#    A3     |   4.5678 V
```

## API Endpoints

### GET /api/ads1115/detect

Detect if ADS1115 is present.

**Query Parameters:**
- `bus` (int, default: 1): I2C bus number
- `addr` (int, default: 72/0x48): I2C address

**Response:**
```json
{
  "ok": true,
  "detected": true,
  "bus": 1,
  "addr": "0x48"
}
```

### GET /api/ads1115/read

Read voltage from an ADS1115 channel.

**Query Parameters:**
- `channel` (int, 0-3): Channel number (A0-A3)
- `bus` (int, default: 1): I2C bus number
- `addr` (int, default: 72/0x48): I2C address
- `pga` (float, default: 4.096): PGA voltage range (volts)

**Response (success):**
```json
{
  "ok": true,
  "channel": 0,
  "voltage": 1.2345,
  "raw_value": 9876,
  "pga": 4.096,
  "bus": 1,
  "addr": "0x48"
}
```

**Response (error - not found):**
```json
{
  "ok": false,
  "error": "ads_not_found",
  "reason": "ADS1115 not found at address 0x48 on bus 1",
  "channel": 0,
  "bus": 1,
  "addr": "0x48"
}
```

**Response (error - read failed):**
```json
{
  "ok": false,
  "error": "read_failed",
  "reason": "Failed to read from ADS1115 channel (I/O error or timeout)",
  "channel": 0,
  "bus": 1,
  "addr": "0x48"
}
```

## Troubleshooting

### "ADS1115 not found"

1. Check I2C connection: `i2cdetect -y 1`
2. Verify user is in i2c group: `groups`
3. Check permissions: `ls -l /dev/i2c-1`
4. Ensure ADS1115 is powered and connected

### "Permission denied" or I/O errors

1. Add user to i2c group: `sudo usermod -a -G i2c $USER`
2. Log out and log back in (group changes require new session)
3. Verify permissions: `ls -l /dev/i2c-1` should show `rw-rw----` and group `i2c`
4. If using udev rules, reload: `sudo udevadm control --reload-rules && sudo udevadm trigger`

### Works with sudo but not without

This indicates a permissions issue. Follow the "Set Up I2C Permissions" section above.

## Implementation Details

- Uses `smbus2` library directly (no Blinka dependencies)
- Retry logic: 3 attempts with 50-100ms delays on I/O errors
- Graceful error handling: Returns `{ok: false}` instead of crashing
- Single-shot mode: Each read triggers a new conversion
- Default settings: 128 SPS, ±4.096V PGA range

