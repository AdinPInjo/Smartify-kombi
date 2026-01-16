"""
Remote client for Smartify Van telemetry and settings sync.
Supports two modes via SMARTIFY_REMOTE_MODE environment variable:
- "local" (default): File-based, no network required
- "http": HTTP-based sync with remote backend (placeholder)
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class RemoteClient:
    """Client for syncing telemetry and settings"""

    def __init__(self, mode: Optional[str] = None):
        """
        Initialize remote client

        Args:
            mode: "local" or "http". If None, reads from SMARTIFY_REMOTE_MODE env var
        """
        self.mode = mode or os.getenv("SMARTIFY_REMOTE_MODE", "local")
        
        if self.mode not in ("local", "http"):
            logger.warning(f"Unknown mode '{self.mode}', defaulting to 'local'")
            self.mode = "local"
        
        logger.info(f"RemoteClient initialized in '{self.mode}' mode")
        
        if self.mode == "local":
            self._init_local_mode()

    def _init_local_mode(self):
        """Initialize local mode directories and files"""
        # Create directories
        self.log_dir = Path("/var/log/smartify")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.config_dir = Path("/etc/smartify")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Define file paths
        self.telemetry_outbox = self.log_dir / "telemetry_outbox.jsonl"
        self.desired_state_file = self.config_dir / "desired_state.json"
        self.ack_state_file = self.log_dir / "ack_state.json"
        
        # Ensure desired_state.json exists with default
        if not self.desired_state_file.exists():
            default_state = {
                "version": 0,
                "desired_state": {}
            }
            try:
                with open(self.desired_state_file, "w") as f:
                    json.dump(default_state, f, indent=2)
                logger.info(f"Created default desired_state.json")
            except Exception as e:
                logger.error(f"Failed to create desired_state.json: {e}")
        
        logger.debug(f"Local mode initialized: outbox={self.telemetry_outbox}")

    def post_telemetry(
        self,
        temperature_c: Optional[float] = None,
        water_percent: Optional[float] = None,
        delta_km: Optional[float] = None,
        gps_lat: Optional[float] = None,
        gps_lon: Optional[float] = None,
        ts: Optional[str] = None,
    ) -> bool:
        """
        Post telemetry data

        In local mode: Appends JSON line to telemetry_outbox.jsonl
        In http mode: Not implemented yet

        Args:
            temperature_c: Temperature in Celsius
            water_percent: Water level percentage (0-100)
            delta_km: Kilometers traveled since last reading
            gps_lat: GPS latitude
            gps_lon: GPS longitude
            ts: ISO timestamp, defaults to now()

        Returns:
            True if successful, False otherwise
        """
        if self.mode == "local":
            return self._post_telemetry_local(
                temperature_c, water_percent, delta_km, gps_lat, gps_lon, ts
            )
        elif self.mode == "http":
            raise NotImplementedError("HTTP mode not implemented yet")
        return False

    def _post_telemetry_local(
        self,
        temperature_c: Optional[float],
        water_percent: Optional[float],
        delta_km: Optional[float],
        gps_lat: Optional[float],
        gps_lon: Optional[float],
        ts: Optional[str],
    ) -> bool:
        """Post telemetry in local mode (append to JSONL file)"""
        try:
            payload = {
                "ts": ts or datetime.now().isoformat(),
                "temperature_c": temperature_c,
                "water_percent": water_percent,
                "delta_km": delta_km,
                "gps_lat": gps_lat,
                "gps_lon": gps_lon,
            }
            
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}
            
            # Append to JSONL file
            with open(self.telemetry_outbox, "a") as f:
                f.write(json.dumps(payload) + "\n")
            
            logger.debug(f"Telemetry appended to {self.telemetry_outbox}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to write telemetry: {e}")
            return False

    def get_desired_state(self) -> Optional[Dict[str, Any]]:
        """
        Get desired state

        In local mode: Reads from /etc/smartify/desired_state.json
        In http mode: Not implemented yet

        Returns:
            Dictionary with 'version' and 'desired_state' keys, or None if failed
        """
        if self.mode == "local":
            return self._get_desired_state_local()
        elif self.mode == "http":
            raise NotImplementedError("HTTP mode not implemented yet")
        return None

    def _get_desired_state_local(self) -> Optional[Dict[str, Any]]:
        """Get desired state in local mode (read from JSON file)"""
        try:
            if not self.desired_state_file.exists():
                logger.warning(f"Desired state file not found: {self.desired_state_file}")
                return {"version": 0, "desired_state": {}}
            
            with open(self.desired_state_file, "r") as f:
                data = json.load(f)
            
            logger.debug(f"Read desired state: version={data.get('version')}")
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in desired_state.json: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to read desired state: {e}")
            return None

    def ack_state(
        self, applied_version: int, current_state: Dict[str, Any]
    ) -> bool:
        """
        Acknowledge that a configuration state has been applied

        In local mode: Writes to /var/log/smartify/ack_state.json
        In http mode: Not implemented yet

        Args:
            applied_version: Version number of applied configuration
            current_state: Current actual state of the device

        Returns:
            True if successful, False otherwise
        """
        if self.mode == "local":
            return self._ack_state_local(applied_version, current_state)
        elif self.mode == "http":
            raise NotImplementedError("HTTP mode not implemented yet")
        return False

    def _ack_state_local(
        self, applied_version: int, current_state: Dict[str, Any]
    ) -> bool:
        """Acknowledge state in local mode (write to JSON file)"""
        try:
            payload = {
                "applied_version": applied_version,
                "current_state": current_state,
                "acknowledged_at": datetime.now().isoformat(),
            }
            
            # Write to JSON file (overwrites previous)
            with open(self.ack_state_file, "w") as f:
                json.dump(payload, f, indent=2)
            
            logger.info(f"State acknowledged: version={applied_version}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to write ack_state: {e}")
            return False

