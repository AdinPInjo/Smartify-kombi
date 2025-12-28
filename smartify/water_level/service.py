"""Water level background service (background thread)."""

import time
import sqlite3
from typing import Dict, Any, Optional
from pathlib import Path

from . import db as water_db
from . import reader
from . import calibration
from .models import WaterLevelSnapshot

# Check if ads1115 is available (for better error messages)
try:
    from smartify import ads1115
except ImportError:
    ads1115 = None


def start_water_level_thread(db_path: Path, app_state: Optional[Dict[str, Any]] = None) -> None:
    """
    Start the background water level sampling thread.
    
    Args:
        db_path: Path to the SQLite database
        app_state: Optional application state dict (for shared cache)
    """
    import threading
    
    def _thread_func():
        _water_level_thread_loop(db_path, app_state)
    
    t = threading.Thread(target=_thread_func, daemon=True, name="WaterLevelThread")
    t.start()
    print("[Water Level] Background thread started")


def _water_level_thread_loop(db_path: Path, app_state: Optional[Dict[str, Any]]) -> None:
    """Background thread loop that samples water level every 60 seconds."""
    
    # Initialize DB path for water_db module
    water_db.set_db_path(db_path)
    
    print("[Water Level] Background thread started")
    
    # Initial delay to allow other systems to start
    time.sleep(5)
    
    # In-memory last good snapshot for fallback
    last_good_snapshot: Optional[Dict[str, Any]] = None
    
    while True:
        try:
            now = int(time.time())
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            
            # Load settings
            settings = water_db.db_get_water_level_settings(conn)
            use_normalization = settings.get("use_supply_normalization", True)
            channel_signal = int(settings.get("adc_channel_signal", 0))
            channel_supply = int(settings.get("adc_channel_supply", 1))
            r_top = float(settings.get("divider_r_top", 47000.0))
            r_bottom = float(settings.get("divider_r_bottom", 10000.0))
            
            # Defensive check: ensure signal and supply channels are different
            if channel_signal == channel_supply:
                print(f"[Water Level] ERROR: Signal and supply channels are the same (A{channel_signal})")
                snapshot = {
                    "avg_voltage": 0.0,
                    "level_percent": 0,
                    "status": "error",
                    "message": f"Invalid configuration: signal and supply channels are both A{channel_signal}",
                    "updated_at": now
                }
                
                # Write to DB with retry
                for retry in range(3):
                    try:
                        conn2 = sqlite3.connect(str(db_path), timeout=5.0)
                        water_db.db_upsert_water_snapshot(conn2, snapshot)
                        conn2.close()
                        break
                    except sqlite3.OperationalError as e:
                        if "database is locked" in str(e) and retry < 2:
                            time.sleep(0.5 * (retry + 1))
                        else:
                            print(f"[Water Level] DB write failed: {e}")
                
                conn.close()
                
                if app_state is not None:
                    # app_state is Starlette State object, use attribute assignment
                    if not hasattr(app_state, 'water_level_latest'):
                        app_state.water_level_latest = {}
                    app_state.water_level_latest = {
                        "level_percent": 0,
                        "avg_voltage": 0.0,
                        "status": "error",
                        "message": f"Invalid configuration: signal and supply channels are both A{channel_signal}",
                        "updated_at": now,
                        "age_seconds": 0
                    }
                
                time.sleep(60)
                continue
            
            # Take 3 samples
            signal_samples = []
            supply_samples = []
            
            for i in range(3):
                signal_v, supply_div_v, _ = reader.read_ads_pair(
                    signal_ch=channel_signal,
                    supply_ch=channel_supply,
                    bus=1,
                    pga=4.096,
                    sps=128
                )
                
                if signal_v is not None:
                    signal_samples.append(signal_v)
                if supply_div_v is not None:
                    supply_samples.append(supply_div_v)
                
                if i < 2:  # Don't sleep after last sample
                    time.sleep(0.1)  # Short delay before next sample pair
            
            conn.close()
            
            # Process readings
            if use_normalization and len(signal_samples) >= 1 and len(supply_samples) >= 1:
                # Normalization mode: use ratio
                avg_signal = sum(signal_samples) / len(signal_samples)
                avg_supply_div = sum(supply_samples) / len(supply_samples)
                
                # Compute supply voltage estimate
                supply_voltage_est = avg_supply_div * (r_top + r_bottom) / r_bottom if r_bottom > 0 else 0.0
                
                # Compute ratio
                ratio = calibration.compute_ratio(avg_signal, supply_voltage_est)
                
                # Get calibration values
                conn = sqlite3.connect(db_path)
                calib_settings = water_db.db_get_water_level_settings(conn)
                conn.close()
                full_ratio_calib = calib_settings.get("full_ratio")
                empty_ratio_calib = calib_settings.get("empty_ratio")
                
                # Convert ratio to percent
                if full_ratio_calib is not None and empty_ratio_calib is not None:
                    level_percent, status, message = calibration.ratio_to_percent(
                        ratio, full_ratio_calib, empty_ratio_calib
                    )
                else:
                    level_percent = 0
                    status = "error"
                    message = "Ratio calibration not configured"
                
                # Debug log once per minute
                print(f"[Water Level] Channels: A{channel_signal}(signal)={avg_signal:.4f}V, "
                      f"A{channel_supply}(supply_div)={avg_supply_div:.4f}V, "
                      f"supply_est={supply_voltage_est:.2f}V, ratio={ratio:.6f}, "
                      f"calib(full={full_ratio_calib}, empty={empty_ratio_calib}), computed={level_percent}%")
                
                # For backward compatibility, avg_voltage is signal voltage
                avg_voltage = avg_signal
                
                # Store snapshot
                snapshot = {
                    "avg_voltage": avg_voltage,
                    "level_percent": level_percent,
                    "status": status,
                    "message": message,
                    "updated_at": now,
                    "avg_signal_voltage": avg_signal,
                    "avg_supply_div_voltage": avg_supply_div,
                    "supply_voltage_est": supply_voltage_est,
                    "ratio": ratio
                }
                
                # Write to DB with retry on lock
                for retry in range(3):
                    try:
                        conn = sqlite3.connect(str(db_path), timeout=5.0)
                        water_db.db_upsert_water_snapshot(conn, snapshot)
                        conn.close()
                        last_good_snapshot = snapshot.copy()
                        break
                    except sqlite3.OperationalError as e:
                        if "database is locked" in str(e) and retry < 2:
                            print(f"[Water Level] DB locked, retry {retry+1}/3...")
                            time.sleep(0.5 * (retry + 1))
                        else:
                            print(f"[Water Level] DB write failed after retries: {e}")
                            # Continue with in-memory snapshot only
                
                # Update in-memory cache if app_state provided
                if app_state is not None:
                    if not hasattr(app_state, 'water_level_latest'):
                        app_state.water_level_latest = {}
                    app_state.water_level_latest = {
                        "level_percent": level_percent,
                        "avg_voltage": avg_voltage,
                        "avg_signal_voltage": avg_signal,
                        "avg_supply_div_voltage": avg_supply_div,
                        "supply_voltage_est": supply_voltage_est,
                        "ratio": ratio,
                        "status": status,
                        "message": message,
                        "updated_at": now,
                        "age_seconds": 0
                    }
                
                print(f"[Water Level] Updated (normalized): {level_percent}% (signal={avg_signal:.3f}V, supply={supply_voltage_est:.3f}V, ratio={ratio:.4f}) - {message}")
            elif len(signal_samples) >= 1:
                # Fallback mode: direct voltage (no normalization or supply read failed)
                avg_voltage = sum(signal_samples) / len(signal_samples)
                
                # Convert to percent using voltage-based method
                conn = sqlite3.connect(db_path)
                settings = water_db.db_get_water_level_settings(conn)
                conn.close()
                full_v = float(settings.get("full_voltage", 0.497))
                empty_v = float(settings.get("empty_voltage", 2.230))
                
                level_percent, status, message = calibration.voltage_to_percent(avg_voltage, full_v, empty_v)
                
                # Store snapshot
                snapshot = {
                    "avg_voltage": avg_voltage,
                    "level_percent": level_percent,
                    "status": status,
                    "message": message,
                    "updated_at": now
                }
                
                # Write to DB with retry on lock
                for retry in range(3):
                    try:
                        conn = sqlite3.connect(str(db_path), timeout=5.0)
                        water_db.db_upsert_water_snapshot(conn, snapshot)
                        conn.close()
                        last_good_snapshot = snapshot.copy()
                        break
                    except sqlite3.OperationalError as e:
                        if "database is locked" in str(e) and retry < 2:
                            print(f"[Water Level] DB locked, retry {retry+1}/3...")
                            time.sleep(0.5 * (retry + 1))
                        else:
                            print(f"[Water Level] DB write failed after retries: {e}")
                            # Continue with in-memory snapshot only
                
                # Update in-memory cache if app_state provided
                if app_state is not None:
                    if not hasattr(app_state, 'water_level_latest'):
                        app_state.water_level_latest = {}
                    app_state.water_level_latest = {
                        "level_percent": level_percent,
                        "avg_voltage": avg_voltage,
                        "status": status,
                        "message": message,
                        "updated_at": now,
                        "age_seconds": 0
                    }
                
                print(f"[Water Level] Updated (voltage-only): {level_percent}% ({avg_voltage:.3f}V) - {message}")
            else:
                # No successful samples
                # Use last good snapshot from memory or DB
                prev_snapshot = last_good_snapshot
                if not prev_snapshot:
                    try:
                        conn = sqlite3.connect(str(db_path), timeout=5.0)
                        prev_snapshot = water_db.db_get_water_level_snapshot(conn)
                        conn.close()
                    except Exception as e:
                        print(f"[Water Level] Failed to read prev snapshot: {e}")
                
                if prev_snapshot:
                    # Keep previous percent but mark as error
                    snapshot = {
                        "avg_voltage": prev_snapshot.get("avg_voltage", 0.0),
                        "level_percent": prev_snapshot.get("level_percent", 0),
                        "status": "error",
                        "message": "I2C read error (ADS1115)" if ads1115 is not None else "ADS1115 module not available",
                        "updated_at": now,
                        "avg_signal_voltage": prev_snapshot.get("avg_signal_voltage"),
                        "avg_supply_div_voltage": prev_snapshot.get("avg_supply_div_voltage"),
                        "supply_voltage_est": prev_snapshot.get("supply_voltage_est"),
                        "ratio": prev_snapshot.get("ratio")
                    }
                    
                    # Write to DB with retry
                    for retry in range(3):
                        try:
                            conn = sqlite3.connect(str(db_path), timeout=5.0)
                            water_db.db_upsert_water_snapshot(conn, snapshot)
                            conn.close()
                            break
                        except sqlite3.OperationalError as e:
                            if "database is locked" in str(e) and retry < 2:
                                print(f"[Water Level] DB locked, retry {retry+1}/3...")
                                time.sleep(0.5 * (retry + 1))
                            else:
                                print(f"[Water Level] DB write failed: {e}")
                    
                    if app_state is not None:
                        if not hasattr(app_state, 'water_level_latest'):
                            app_state.water_level_latest = {}
                        app_state.water_level_latest = {
                            "level_percent": prev_snapshot.get("level_percent"),
                            "avg_voltage": prev_snapshot.get("avg_voltage"),
                            "status": "error",
                            "message": "I2C read error (ADS1115)",
                            "updated_at": prev_snapshot.get("updated_at", now),
                            "age_seconds": now - prev_snapshot.get("updated_at", now)
                        }
                else:
                    # No previous snapshot - create error snapshot
                    snapshot = {
                        "avg_voltage": 0.0,
                        "level_percent": 0,
                        "status": "error",
                        "message": "I2C read error (ADS1115)" if ads1115 is not None else "ADS1115 module not available",
                        "updated_at": now
                    }
                    
                    # Write to DB with retry
                    for retry in range(3):
                        try:
                            conn = sqlite3.connect(str(db_path), timeout=5.0)
                            water_db.db_upsert_water_snapshot(conn, snapshot)
                            conn.close()
                            break
                        except sqlite3.OperationalError as e:
                            if "database is locked" in str(e) and retry < 2:
                                print(f"[Water Level] DB locked, retry {retry+1}/3...")
                                time.sleep(0.5 * (retry + 1))
                            else:
                                print(f"[Water Level] DB write failed: {e}")
                    
                    if app_state is not None:
                        if not hasattr(app_state, 'water_level_latest'):
                            app_state.water_level_latest = {}
                        app_state.water_level_latest = {
                            "level_percent": 0,
                            "avg_voltage": 0.0,
                            "status": "error",
                            "message": "I2C read error (ADS1115)",
                            "updated_at": now,
                            "age_seconds": 0
                        }
                
                print(f"[Water Level] Error: Failed to read ADS1115")
        
        except Exception as e:
            print(f"[Water Level] Exception in background thread: {e}")
            import traceback
            traceback.print_exc()
            # Continue running - don't crash the thread
        
        # Wait 60 seconds before next sample
        time.sleep(60)

