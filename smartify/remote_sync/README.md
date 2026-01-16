# Smartify Remote Sync - Local Mode

Pi-first remote sync implementation that works **without any cloud dependency**.

## Architecture

### Local Mode (Default)

**File-based, no network required:**

```
┌─────────────────────────────────────────────────────┐
│  Raspberry Pi                                        │
│                                                       │
│  ┌─────────────────────────────────────────┐        │
│  │  runner.py (Main Service)               │        │
│  │                                           │        │
│  │  Telemetry Loop (60s)  Settings Loop (15s)│       │
│  │  ├─ Read sensors      ├─ Read file        │      │
│  │  ├─ Calc delta_km     ├─ Check version    │      │
│  │  └─ Append JSONL      └─ Apply & ACK      │      │
│  └─────────────────────────────────────────┘        │
│           │                        │                  │
│           ▼                        ▼                  │
│  ┌───────────────────────────────────────┐          │
│  │  Local Files (no network)             │          │
│  │                                         │          │
│  │  /var/log/smartify/                   │          │
│  │  ├─ telemetry_outbox.jsonl ← append  │          │
│  │  └─ ack_state.json         ← write   │          │
│  │                                         │          │
│  │  /etc/smartify/                       │          │
│  │  └─ desired_state.json     ← read    │          │
│  │                                         │          │
│  │  /var/lib/smartify/                   │          │
│  │  ├─ applied_version.txt    ← rw       │          │
│  │  └─ last_gps.json          ← rw       │          │
│  └───────────────────────────────────────┘          │
└─────────────────────────────────────────────────────┘
```

**Benefits:**
- ✅ Works offline
- ✅ No cloud dependencies
- ✅ Simple file-based storage
- ✅ Easy to inspect and debug
- ✅ Can be synced to cloud later

### HTTP Mode (Placeholder)

For future cloud sync - not yet implemented. Set `SMARTIFY_REMOTE_MODE=http` to use (will raise NotImplementedError).

## Files

### `remote_client.py`
Client that supports two modes:

**Local mode (default):**
- `post_telemetry()` → Append to `/var/log/smartify/telemetry_outbox.jsonl`
- `get_desired_state()` → Read from `/etc/smartify/desired_state.json`
- `ack_state()` → Write to `/var/log/smartify/ack_state.json`

**HTTP mode (placeholder):**
- Raises `NotImplementedError` for now
- Can be implemented later for cloud sync

### `runner.py`
Main service with two loops:

**Telemetry Loop (60s):**
1. Read temperature via `adapters.read_temperature()`
2. Read water level via `adapters.read_water_level()`
3. Read GPS via `adapters.read_gps_location()`
4. Calculate `delta_km` if GPS available
5. Append telemetry to JSONL file
6. Store GPS position for next delta calculation

**Settings Loop (15s):**
1. Read desired state from JSON file
2. Compare version with local applied_version
3. Apply new settings if version is higher
4. Write acknowledgment to JSON file
5. Update local applied_version

### `adapters.py`
Clean interface to existing smartify sensors and controls:

**Sensors:**
- `read_temperature()` → Celsius
- `read_water_level()` → Percentage
- `read_gps_location()` → {latitude, longitude}

**Controls:**
- `apply_heater_setting(enabled)`
- `apply_pump_setting(enabled)`
- `apply_lighting_mode(mode)`
- `apply_target_temperature(temp_c)`
- `apply_desired_state(desired_state)` → current_state

**Note:** Update imports in `adapters.py` to match your actual module paths.

## Installation

### Quick Install

```bash
cd /home/pi/smartify/deploy
./install_remote_sync.sh
```

The script will:
1. Create required directories with proper permissions
2. Create default `desired_state.json` if needed
3. Install systemd service
4. Enable service (start on boot)
5. Optionally start immediately

### Manual Install

```bash
# Create directories
sudo mkdir -p /var/log/smartify /var/lib/smartify /etc/smartify
sudo chown pi:pi /var/log/smartify /var/lib/smartify /etc/smartify

# Create default desired_state.json
cat > /etc/smartify/desired_state.json <<EOF
{
  "version": 0,
  "desired_state": {}
}
EOF

# Install service
sudo cp deploy/smartify-remote-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smartify-remote-sync
sudo systemctl start smartify-remote-sync
```

## Usage

### Service Management

```bash
# Check status
sudo systemctl status smartify-remote-sync

# View logs
tail -f /var/log/smartify/remote_sync.log

# Restart
sudo systemctl restart smartify-remote-sync

# Stop/Start
sudo systemctl stop smartify-remote-sync
sudo systemctl start smartify-remote-sync
```

### Viewing Telemetry

```bash
# View telemetry outbox (JSONL format)
tail -f /var/log/smartify/telemetry_outbox.jsonl

# Pretty print last telemetry entry
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq

# Count telemetry entries
wc -l /var/log/smartify/telemetry_outbox.jsonl
```

### Updating Settings

Edit `/etc/smartify/desired_state.json` and **increment the version**:

```json
{
  "version": 1,
  "desired_state": {
    "heaterEnabled": true,
    "pumpEnabled": false,
    "lightingMode": "dim",
    "targetTemperature": 21
  }
}
```

The runner will detect the change within 15 seconds and apply it.

### Checking Applied Settings

```bash
# View acknowledged state
cat /var/log/smartify/ack_state.json | jq

# Check applied version
cat /var/lib/smartify/applied_version.txt
```

## File Locations

| File | Purpose | Format |
|------|---------|--------|
| `/var/log/smartify/telemetry_outbox.jsonl` | Telemetry data (append) | JSONL |
| `/var/log/smartify/ack_state.json` | Settings acknowledgment | JSON |
| `/var/log/smartify/remote_sync.log` | Service logs | Text |
| `/etc/smartify/desired_state.json` | Desired configuration | JSON |
| `/var/lib/smartify/applied_version.txt` | Applied settings version | Text |
| `/var/lib/smartify/last_gps.json` | Last GPS position | JSON |

## Configuration

### Environment Variables

Set in the systemd service file:

**`SMARTIFY_REMOTE_MODE`**
- `local` (default) - File-based, no network
- `http` - HTTP-based sync (not implemented yet)

### Loop Intervals

Edit `runner.py` to change intervals:

```python
# Telemetry loop (default: 60 seconds)
telemetry_thread = threading.Thread(
    target=telemetry_loop,
    args=(client, state_manager, 60),  # <-- Change here
)

# Settings loop (default: 15 seconds)
settings_thread = threading.Thread(
    target=settings_loop,
    args=(client, state_manager, 15),  # <-- Change here
)
```

## Integrating Your Code

### Update Sensor Adapters

Edit `remote_sync/adapters.py` and update the imports:

```python
# Update these to match your actual modules
from smartify.temp_logger import read_temperature as _read_temp
from smartify.water_level.reader import WaterLevelReader
from smartify.gps_logger import get_current_location
```

### Update Control Adapters

Replace the placeholder control functions in `adapters.py`:

```python
def apply_heater_setting(enabled: bool) -> bool:
    # Replace with your actual control function
    from smartify.controls import set_heater
    return set_heater(enabled)
```

## Monitoring

### Check Service Status

```bash
# Is service running?
sudo systemctl is-active smartify-remote-sync

# Service status
sudo systemctl status smartify-remote-sync

# Recent logs
journalctl -u smartify-remote-sync -n 50
```

### Check Data Flow

```bash
# Telemetry rate (entries per minute)
tail -60 /var/log/smartify/telemetry_outbox.jsonl | wc -l

# Last telemetry timestamp
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq -r .ts

# Settings version check
echo "Desired: $(jq -r .version /etc/smartify/desired_state.json)"
echo "Applied: $(cat /var/lib/smartify/applied_version.txt)"
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u smartify-remote-sync -n 100

# Check for errors
grep ERROR /var/log/smartify/remote_sync.log

# Check permissions
ls -la /var/log/smartify/
ls -la /var/lib/smartify/
ls -la /etc/smartify/
```

### No Telemetry Data

1. Check if service is running:
   ```bash
   sudo systemctl status smartify-remote-sync
   ```

2. Check sensor adapters:
   ```bash
   # Test temperature
   python3 -c "from remote_sync.adapters import read_temperature; print(read_temperature())"
   ```

3. Check telemetry file:
   ```bash
   ls -lh /var/log/smartify/telemetry_outbox.jsonl
   tail /var/log/smartify/telemetry_outbox.jsonl
   ```

### Settings Not Applying

1. Check version numbers:
   ```bash
   echo "Desired: $(jq -r .version /etc/smartify/desired_state.json)"
   echo "Applied: $(cat /var/lib/smartify/applied_version.txt)"
   ```

2. Check logs for version comparison:
   ```bash
   grep "Version check" /var/log/smartify/remote_sync.log | tail -5
   ```

3. Increment version in desired_state.json

### Sensor Errors

If a sensor fails, the service continues with available sensors:

```bash
# Check logs for sensor errors
grep "Error reading" /var/log/smartify/remote_sync.log
```

Fix sensor imports in `adapters.py` as needed.

## Performance

**Resource usage:**
- CPU: < 2%
- Memory: < 30 MB
- Disk: ~1 MB/day (telemetry JSONL)

**Typical telemetry entry size:** ~150 bytes

## Data Format Examples

### Telemetry Entry (JSONL)

```json
{"ts": "2026-01-16T15:30:45.123456", "temperature_c": 22.5, "water_percent": 68.0, "delta_km": 2.3, "gps_lat": 48.8566, "gps_lon": 2.3522}
```

### Desired State

```json
{
  "version": 3,
  "desired_state": {
    "heaterEnabled": false,
    "pumpEnabled": true,
    "lightingMode": "dim",
    "targetTemperature": 21
  }
}
```

### ACK State

```json
{
  "applied_version": 3,
  "current_state": {
    "heaterEnabled": false,
    "pumpEnabled": true,
    "lightingMode": "dim",
    "targetTemperature": 21,
    "currentTemperature": 22.5,
    "currentWaterLevel": 68.0
  },
  "acknowledged_at": "2026-01-16T15:30:50.123456"
}
```

## Future: Cloud Sync

To add HTTP mode later:

1. Implement HTTP functions in `remote_client.py`
2. Set `SMARTIFY_REMOTE_MODE=http` in service file
3. Add environment variables for cloud URL and token
4. Optional: Add background process to sync local JSONL to cloud

The local mode files can still be used for offline operation and as a backup.

## License

Part of the Smartify Van project.

