"""
Remote client for Smartify Van telemetry and settings sync.
Supports two modes via SMARTIFY_REMOTE_MODE environment variable:
- "local" (default): File-based, no network required
- "http": HTTP-based sync with Supabase Edge Functions
"""

import os
import json
import logging
import time
import requests
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
        elif self.mode == "http":
            self._init_http_mode()

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
    
    def _init_http_mode(self):
        """Initialize HTTP mode configuration"""
        self.base_url = os.getenv("SMARTIFY_REMOTE_BASE_URL", "").strip()
        self.device_token = os.getenv("SMARTIFY_DEVICE_TOKEN", "").strip()
        self.supabase_anon_key = os.getenv("SMARTIFY_SUPABASE_ANON_KEY", "").strip()
        
        # Read device_id from environment (multiple possible names for compatibility)
        self.device_id = (
            os.getenv("SMARTIFY_DEVICE_ID", "").strip() or
            os.getenv("DEVICE_ID", "").strip() or
            os.getenv("REMOTE_DEVICE_ID", "").strip()
        )
        
        # Validate required configuration
        if not self.base_url:
            logger.error("SMARTIFY_REMOTE_BASE_URL not set for HTTP mode")
            raise ValueError("SMARTIFY_REMOTE_BASE_URL is required for HTTP mode")
        
        if not self.device_token:
            logger.error("SMARTIFY_DEVICE_TOKEN not set for HTTP mode")
            raise ValueError("SMARTIFY_DEVICE_TOKEN is required for HTTP mode")
        
        if not self.supabase_anon_key:
            logger.error("SMARTIFY_SUPABASE_ANON_KEY not set for HTTP mode")
            raise ValueError("SMARTIFY_SUPABASE_ANON_KEY is required for HTTP mode")
        
        if not self.device_id:
            logger.warning("SMARTIFY_DEVICE_ID not set - getDesiredState will not work properly")
            # Don't raise error - allow telemetry to work, just warn about desired_state
        
        # Remove trailing slash from base URL
        self.base_url = self.base_url.rstrip('/')
        
        # Setup HTTP session with headers for Supabase Edge Functions
        # Authorization and apikey use the Supabase anon key (for gateway)
        # x-device-token contains the device authentication token
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.supabase_anon_key}',
            'apikey': self.supabase_anon_key,
            'x-device-token': self.device_token,
        })
        
        # HTTP timeouts and retry settings
        self.http_timeout = 5  # seconds
        self.http_retries = 3
        self.http_backoff = 0.5  # seconds
        
        logger.info(f"HTTP mode initialized: base_url={self.base_url}")
        if self.device_id:
            logger.info(f"Device ID configured: {self.device_id}")
        logger.debug(f"Device token configured (length={len(self.device_token)})")
        logger.debug(f"Supabase anon key configured (length={len(self.supabase_anon_key)})")

    def post_telemetry(
        self,
        temperature_c: Optional[float] = None,
        water_percent: Optional[float] = None,
        delta_km: Optional[float] = None,
        gps_lat: Optional[float] = None,
        gps_lon: Optional[float] = None,
        relays: Optional[dict] = None,
        ts: Optional[str] = None,
    ) -> bool:
        """
        Post telemetry data

        In local mode: Appends JSON line to telemetry_outbox.jsonl
        In http mode: POST to Supabase Edge Function

        Args:
            temperature_c: Temperature in Celsius
            water_percent: Water level percentage (0-100)
            delta_km: Kilometers traveled since last reading
            gps_lat: GPS latitude
            gps_lon: GPS longitude
            relays: Relay states dict, e.g. {"heater": "on", "pump": "off"}
            ts: ISO timestamp, defaults to now()

        Returns:
            True if successful, False otherwise
        """
        if self.mode == "local":
            return self._post_telemetry_local(
                temperature_c, water_percent, delta_km, gps_lat, gps_lon, relays, ts
            )
        elif self.mode == "http":
            return self._post_telemetry_http(
                temperature_c, water_percent, delta_km, gps_lat, gps_lon, relays, ts
            )
        return False

    def _post_telemetry_local(
        self,
        temperature_c: Optional[float],
        water_percent: Optional[float],
        delta_km: Optional[float],
        gps_lat: Optional[float],
        gps_lon: Optional[float],
        relays: Optional[dict],
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
                "relays": relays,
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
    
    def _post_telemetry_http(
        self,
        temperature_c: Optional[float],
        water_percent: Optional[float],
        delta_km: Optional[float],
        gps_lat: Optional[float],
        gps_lon: Optional[float],
        relays: Optional[dict],
        ts: Optional[str],
    ) -> bool:
        """Post telemetry in HTTP mode (to Supabase Edge Function)"""
        payload = {
            "temperature_c": temperature_c,
            "water_percent": water_percent,
            "delta_km": delta_km,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "relays": relays,
            "ts": ts or datetime.now().isoformat(),
        }
        
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        url = f"{self.base_url}/ingestTelemetry"
        
        for attempt in range(self.http_retries):
            try:
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.http_timeout
                )
                
                if response.status_code == 200:
                    logger.info(f"Telemetry posted successfully to remote")
                    return True
                else:
                    logger.warning(
                        f"Telemetry post failed (attempt {attempt + 1}/{self.http_retries}): "
                        f"status={response.status_code}, response={response.text[:500]}"
                    )
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Telemetry post timeout (attempt {attempt + 1}/{self.http_retries})")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Telemetry post error (attempt {attempt + 1}/{self.http_retries}): {e}")
            except Exception as e:
                logger.error(f"Unexpected error posting telemetry: {e}")
                return False
            
            # Backoff before retry
            if attempt < self.http_retries - 1:
                time.sleep(self.http_backoff * (2 ** attempt))
        
        logger.error(f"Failed to post telemetry after {self.http_retries} attempts")
        return False

    def get_desired_state(self) -> Optional[Dict[str, Any]]:
        """
        Get desired state

        In local mode: Reads from /etc/smartify/desired_state.json
        In http mode: GET from Supabase Edge Function

        Returns:
            Dictionary with 'version' and 'desired_state' keys, or None if failed
        """
        if self.mode == "local":
            return self._get_desired_state_local()
        elif self.mode == "http":
            return self._get_desired_state_http()
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
    
    def _get_desired_state_http(self) -> Optional[Dict[str, Any]]:
        """
        Get desired state in HTTP mode (from Supabase Edge Function)
        
        Sends device_id in POST request body to identify which device's settings to fetch.
        
        Returns:
            Dictionary with 'version' and 'desired_state' keys, or None if failed
        """
        # Check if device_id is configured
        if not self.device_id:
            logger.error("SMARTIFY_DEVICE_ID not set - cannot fetch desired state")
            return {"version": 0, "desired_state": {}}
        
        url = f"{self.base_url}/getDesiredState"
        
        # Prepare request payload with device_id
        payload = {
            "device_id": self.device_id
        }
        
        for attempt in range(self.http_retries):
            try:
                # Use POST with JSON body (Edge Function expects device_id in body)
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.http_timeout
                )
                
                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"Got desired state from remote: version={data.get('version')}")
                    return data
                elif response.status_code == 404:
                    logger.debug("No desired state configured yet")
                    return {"version": 0, "desired_state": {}}
                else:
                    logger.warning(
                        f"Get desired state failed (attempt {attempt + 1}/{self.http_retries}): "
                        f"status={response.status_code}, response={response.text[:500]}"
                    )
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Get desired state timeout (attempt {attempt + 1}/{self.http_retries})")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Get desired state error (attempt {attempt + 1}/{self.http_retries}): {e}")
            except Exception as e:
                logger.error(f"Unexpected error getting desired state: {e}")
                return None
            
            # Backoff before retry
            if attempt < self.http_retries - 1:
                time.sleep(self.http_backoff * (2 ** attempt))
        
        logger.error(f"Failed to get desired state after {self.http_retries} attempts")
        return None

    def ack_state(
        self, applied_version: int, current_state: Dict[str, Any]
    ) -> bool:
        """
        Acknowledge that a configuration state has been applied

        In local mode: Writes to /var/log/smartify/ack_state.json
        In http mode: POST to Supabase Edge Function

        Args:
            applied_version: Version number of applied configuration
            current_state: Current actual state of the device

        Returns:
            True if successful, False otherwise
        """
        if self.mode == "local":
            return self._ack_state_local(applied_version, current_state)
        elif self.mode == "http":
            return self._ack_state_http(applied_version, current_state)
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
    
    def _ack_state_http(
        self, applied_version: int, current_state: Dict[str, Any]
    ) -> bool:
        """Acknowledge state in HTTP mode (to Supabase Edge Function)"""
        payload = {
            "applied_version": applied_version,
            "current_state": current_state,
        }
        
        url = f"{self.base_url}/ackState"
        
        for attempt in range(self.http_retries):
            try:
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.http_timeout
                )
                
                if response.status_code == 200:
                    logger.info(f"State acknowledged to remote: version={applied_version}")
                    return True
                else:
                    logger.warning(
                        f"Ack state failed (attempt {attempt + 1}/{self.http_retries}): "
                        f"status={response.status_code}, response={response.text[:500]}"
                    )
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Ack state timeout (attempt {attempt + 1}/{self.http_retries})")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Ack state error (attempt {attempt + 1}/{self.http_retries}): {e}")
            except Exception as e:
                logger.error(f"Unexpected error acknowledging state: {e}")
                return False
            
            # Backoff before retry
            if attempt < self.http_retries - 1:
                time.sleep(self.http_backoff * (2 ** attempt))
        
        logger.error(f"Failed to acknowledge state after {self.http_retries} attempts")
        return False

