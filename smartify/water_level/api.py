"""Water level FastAPI router."""

import time
import sqlite3
from typing import Optional, Dict, Any, Callable
from pathlib import Path
from fastapi import APIRouter, Request, Header, Body
from fastapi.responses import JSONResponse

from . import db as water_db
from . import reader
from . import calibration

# Cache for live reads (prevents hammering I2C)
_live_read_cache: Optional[Dict[str, Any]] = None
_live_read_cache_time: float = 0.0
CACHE_TTL_SECONDS = 0.5  # Cache for 500ms

# Module-level router (will be initialized by init_router)
router: Optional[APIRouter] = None
_db_path: Optional[Path] = None
_require_auth_func: Optional[Callable] = None


def init_router(db_path: Path, require_auth_func: Callable, app_state: Optional[Dict[str, Any]] = None) -> None:
    """
    Initialize the module-level router.
    
    Must be called before using router.
    
    Args:
        db_path: Path to SQLite database
        require_auth_func: Function that checks authentication (returns error response or None)
        app_state: Optional application state dict (for shared cache)
    """
    global router, _db_path, _require_auth_func
    _db_path = db_path
    _require_auth_func = require_auth_func
    router = _create_router(db_path, require_auth_func, app_state)


def _create_router(db_path: Path, require_auth_func, app_state: Optional[Dict[str, Any]] = None) -> APIRouter:
    """
    Create FastAPI router for water level endpoints.
    
    Args:
        db_path: Path to SQLite database
        require_auth_func: Function that checks authentication (returns error response or None)
        app_state: Optional application state dict (for shared cache)
    
    Returns:
        FastAPI router with water level endpoints
    """
    router = APIRouter(prefix="/api/water", tags=["water"])
    
    # Initialize DB path for water_db module
    water_db.set_db_path(db_path)
    
    @router.get("/settings")
    def api_water_settings_get(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        """Get water level calibration settings. Always HTTP 200, never crashes."""
        err = require_auth_func(request, x_api_key)
        if err:
            return err
        
        try:
            conn = sqlite3.connect(db_path)
            settings = water_db.db_get_water_level_settings(conn)
            conn.close()
            
            return JSONResponse({
                "ok": True,
                "full_voltage": float(settings.get("full_voltage", 0.497)),
                "empty_voltage": float(settings.get("empty_voltage", 2.230)),
                "use_supply_normalization": bool(settings.get("use_supply_normalization", True)),
                "adc_channel_signal": int(settings.get("adc_channel_signal", 0)),
                "adc_channel_supply": int(settings.get("adc_channel_supply", 1)),
                "divider_r_top": float(settings.get("divider_r_top", 47000.0)),
                "divider_r_bottom": float(settings.get("divider_r_bottom", 10000.0)),
                "full_ratio": float(settings.get("full_ratio")) if settings.get("full_ratio") is not None else None,
                "empty_ratio": float(settings.get("empty_ratio")) if settings.get("empty_ratio") is not None else None,
                "full_supply_voltage": float(settings.get("full_supply_voltage")) if settings.get("full_supply_voltage") is not None else None,
                "empty_supply_voltage": float(settings.get("empty_supply_voltage")) if settings.get("empty_supply_voltage") is not None else None,
                "updated_at": int(settings.get("updated_at", 0))
            })
        except Exception as e:
            print(f"[API] Error in /api/water/settings GET: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse({
                "ok": False,
                "error": "internal_error",
                "full_voltage": 0.497,
                "empty_voltage": 2.230,
                "updated_at": 0,
                "message": f"Internal error: {str(e)}"
            })
    
    @router.post("/settings")
    def api_water_settings_post(
        request: Request,
        body: Dict[str, Any] = Body(...),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        """Update water level calibration settings. Always HTTP 200."""
        err = require_auth_func(request, x_api_key)
        if err:
            return err
        
        try:
            # Get all possible fields from request body
            full_voltage = body.get("full_voltage")
            empty_voltage = body.get("empty_voltage")
            use_supply_normalization = body.get("use_supply_normalization")
            adc_channel_signal = body.get("adc_channel_signal")
            adc_channel_supply = body.get("adc_channel_supply")
            divider_r_top = body.get("divider_r_top")
            divider_r_bottom = body.get("divider_r_bottom")
            full_ratio = body.get("full_ratio")
            empty_ratio = body.get("empty_ratio")
            full_supply_voltage = body.get("full_supply_voltage")
            empty_supply_voltage = body.get("empty_supply_voltage")
            
            # Validate voltage-based calibration if provided
            if full_voltage is not None or empty_voltage is not None:
                if full_voltage is None or empty_voltage is None:
                    return JSONResponse({
                        "ok": False,
                        "error": "missing_fields",
                        "message": "Both full_voltage and empty_voltage must be provided together"
                    })
                
                try:
                    full_voltage = float(full_voltage)
                    empty_voltage = float(empty_voltage)
                except (ValueError, TypeError):
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_type",
                        "message": "full_voltage and empty_voltage must be numbers"
                    })
                
                EPSILON = 0.001
                if full_voltage <= 0 or empty_voltage <= 0:
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_value",
                        "message": "Voltages must be positive numbers"
                    })
                
                if abs(full_voltage - empty_voltage) < EPSILON:
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_value",
                        "message": "Full and empty voltages must be different"
                    })
            
            # Validate ratio-based calibration if provided
            if full_ratio is not None or empty_ratio is not None:
                if full_ratio is None or empty_ratio is None:
                    return JSONResponse({
                        "ok": False,
                        "error": "missing_fields",
                        "message": "Both full_ratio and empty_ratio must be provided together"
                    })
                
                try:
                    full_ratio = float(full_ratio)
                    empty_ratio = float(empty_ratio)
                except (ValueError, TypeError):
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_type",
                        "message": "full_ratio and empty_ratio must be numbers"
                    })
                
                # Validate ratio values using calibration module
                use_norm = use_supply_normalization if use_supply_normalization is not None else True
                error_msg = calibration.validate_ratio_values(full_ratio, empty_ratio, use_norm)
                if error_msg:
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_value",
                        "message": error_msg
                    })
            
            # Validate other fields
            if use_supply_normalization is not None:
                use_supply_normalization = bool(use_supply_normalization)
            
            if adc_channel_signal is not None:
                try:
                    adc_channel_signal = int(adc_channel_signal)
                    if adc_channel_signal not in (0, 1, 2, 3):
                        return JSONResponse({
                            "ok": False,
                            "error": "invalid_value",
                            "message": "adc_channel_signal must be 0-3"
                        })
                except (ValueError, TypeError):
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_type",
                        "message": "adc_channel_signal must be an integer"
                    })
            
            if adc_channel_supply is not None:
                try:
                    adc_channel_supply = int(adc_channel_supply)
                    if adc_channel_supply not in (0, 1, 2, 3):
                        return JSONResponse({
                            "ok": False,
                            "error": "invalid_value",
                            "message": "adc_channel_supply must be 0-3"
                        })
                except (ValueError, TypeError):
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_type",
                        "message": "adc_channel_supply must be an integer"
                    })
            
            if divider_r_top is not None:
                try:
                    divider_r_top = float(divider_r_top)
                    if divider_r_top <= 0:
                        return JSONResponse({
                            "ok": False,
                            "error": "invalid_value",
                            "message": "divider_r_top must be positive"
                        })
                except (ValueError, TypeError):
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_type",
                        "message": "divider_r_top must be a number"
                    })
            
            if divider_r_bottom is not None:
                try:
                    divider_r_bottom = float(divider_r_bottom)
                    if divider_r_bottom <= 0:
                        return JSONResponse({
                            "ok": False,
                            "error": "invalid_value",
                            "message": "divider_r_bottom must be positive"
                        })
                except (ValueError, TypeError):
                    return JSONResponse({
                        "ok": False,
                        "error": "invalid_type",
                        "message": "divider_r_bottom must be a number"
                    })
            
            # Save to DB
            conn = sqlite3.connect(db_path)
            settings = water_db.db_update_water_level_settings(
                conn,
                full_voltage=full_voltage,
                empty_voltage=empty_voltage,
                use_supply_normalization=use_supply_normalization,
                adc_channel_signal=adc_channel_signal,
                adc_channel_supply=adc_channel_supply,
                divider_r_top=divider_r_top,
                divider_r_bottom=divider_r_bottom,
                full_ratio=full_ratio,
                empty_ratio=empty_ratio,
                full_supply_voltage=full_supply_voltage,
                empty_supply_voltage=empty_supply_voltage
            )
            conn.close()
            
            # Log saved values
            print(f"[Water Level Settings POST] Saved values: "
                  f"use_normalization={settings.get('use_supply_normalization')}, "
                  f"full_ratio={settings.get('full_ratio')}, empty_ratio={settings.get('empty_ratio')}, "
                  f"full_voltage={settings.get('full_voltage')}, empty_voltage={settings.get('empty_voltage')}")
            
            return JSONResponse({
                "ok": True,
                "full_voltage": float(settings.get("full_voltage", 0.497)),
                "empty_voltage": float(settings.get("empty_voltage", 2.230)),
                "use_supply_normalization": bool(settings.get("use_supply_normalization", True)),
                "adc_channel_signal": int(settings.get("adc_channel_signal", 0)),
                "adc_channel_supply": int(settings.get("adc_channel_supply", 1)),
                "divider_r_top": float(settings.get("divider_r_top", 47000.0)),
                "divider_r_bottom": float(settings.get("divider_r_bottom", 10000.0)),
                "full_ratio": float(settings.get("full_ratio")) if settings.get("full_ratio") is not None else None,
                "empty_ratio": float(settings.get("empty_ratio")) if settings.get("empty_ratio") is not None else None,
                "full_supply_voltage": float(settings.get("full_supply_voltage")) if settings.get("full_supply_voltage") is not None else None,
                "empty_supply_voltage": float(settings.get("empty_supply_voltage")) if settings.get("empty_supply_voltage") is not None else None,
                "updated_at": int(settings.get("updated_at", 0))
            })
        
        except Exception as e:
            print(f"[API] Error in /api/water/settings POST: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse({
                "ok": False,
                "error": "internal_error",
                "message": f"Internal error: {str(e)}"
            })
    
    @router.get("/level/live")
    def api_water_level_live(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        """
        Get live voltage reading from ADS1115.
        
        Cached for 0.5 seconds to prevent hammering I2C.
        Takes 3 quick reads of both channels and averages them for stability.
        """
        global _live_read_cache, _live_read_cache_time
        
        err = require_auth_func(request, x_api_key)
        if err:
            return err
        
        # Check cache
        now_ts = time.time()
        if _live_read_cache is not None and (now_ts - _live_read_cache_time) < CACHE_TTL_SECONDS:
            return JSONResponse(_live_read_cache)
        
        try:
            # Load settings
            conn = sqlite3.connect(db_path)
            settings = water_db.db_get_water_level_settings(conn)
            conn.close()
            
            use_normalization = settings.get("use_supply_normalization", True)
            channel_signal = int(settings.get("adc_channel_signal", 0))
            channel_supply = int(settings.get("adc_channel_supply", 1))
            r_top = float(settings.get("divider_r_top", 47000.0))
            r_bottom = float(settings.get("divider_r_bottom", 10000.0))
            
            # DIAGNOSTIC: Log channel configuration
            print(f"[Water Level Live] CONFIG: adc_channel_signal=A{channel_signal}, adc_channel_supply=A{channel_supply}, use_normalization={use_normalization}")
            
            # Defensive check
            if channel_signal == channel_supply:
                result = {
                    "ok": False,
                    "signal_voltage": None,
                    "supply_div_voltage": None,
                    "supply_voltage_est": None,
                    "ratio": None,
                    "level_percent": None,
                    "address": "0x48",
                    "status": "error",
                    "message": f"Invalid configuration: signal and supply channels are both A{channel_signal}"
                }
                _live_read_cache = result
                _live_read_cache_time = now_ts
                return JSONResponse(result)
            
            # Take 3 samples
            signal_samples = []
            supply_samples = []
            detected_address = None
            
            for i in range(3):
                signal_v, supply_div_v, addr = reader.read_ads_pair(
                    signal_ch=channel_signal,
                    supply_ch=channel_supply,
                    bus=1,
                    pga=4.096,
                    sps=128
                )
                
                if addr:
                    detected_address = addr
                
                # DIAGNOSTIC: Log raw tuple from ads_read_voltage_pair
                if i == 0:
                    print(f"[Water Level Live] RAW TUPLE from ads_read_voltage_pair(ch0={channel_signal}, ch1={channel_supply}): "
                          f"v0={signal_v}, v1={supply_div_v}, addr={addr}")
                
                if signal_v is not None:
                    signal_samples.append(signal_v)
                if supply_div_v is not None:
                    supply_samples.append(supply_div_v)
                
                if i < 2:
                    time.sleep(0.1)  # Short delay before next sample pair
            
            if len(signal_samples) >= 1:
                avg_signal = sum(signal_samples) / len(signal_samples)
                
                # Check for mirrored channels (warning, not hard fail)
                if use_normalization and len(supply_samples) >= 1:
                    avg_supply_div = sum(supply_samples) / len(supply_samples)
                    diff = abs(avg_signal - avg_supply_div)
                    
                    # Warn if mirrored but still return data
                    if diff < 0.01:  # 10mV threshold
                        print(f"[Water Level Live] WARNING: Channels appear mirrored (diff={diff:.6f}V)")
                        # Still continue processing - don't hard fail
                    
                    supply_voltage_est = avg_supply_div * (r_top + r_bottom) / r_bottom if r_bottom > 0 else 0.0
                    ratio = calibration.compute_ratio(avg_signal, supply_voltage_est)
                    
                    # Get calibration for percent calculation
                    conn = sqlite3.connect(db_path)
                    calib_settings = water_db.db_get_water_level_settings(conn)
                    conn.close()
                    full_ratio_calib = calib_settings.get("full_ratio")
                    empty_ratio_calib = calib_settings.get("empty_ratio")
                    
                    if full_ratio_calib is not None and empty_ratio_calib is not None:
                        level_percent, status, message = calibration.ratio_to_percent(
                            ratio, full_ratio_calib, empty_ratio_calib
                        )
                    else:
                        level_percent = None
                        status = "error"
                        message = "Ratio calibration not configured"
                    
                    result = {
                        "ok": True,
                        "signal_voltage": float(avg_signal),
                        "supply_div_voltage": float(avg_supply_div),
                        "supply_voltage_est": float(supply_voltage_est),
                        "ratio": float(ratio),
                        "level_percent": int(level_percent) if level_percent is not None else None,
                        "address": detected_address or "0x48",
                        "status": status,
                        "message": message
                    }
                    # DIAGNOSTIC: Log final JSON response values
                    print(f"[Water Level Live] RESPONSE: signal_voltage={result['signal_voltage']:.6f}V, "
                          f"supply_div_voltage={result['supply_div_voltage']:.6f}V, "
                          f"ratio={result['ratio']:.4f}, level_percent={result['level_percent']}%, "
                          f"ok={result['ok']}, status={result['status']}")
                else:
                    # Fallback: signal only
                    conn = sqlite3.connect(db_path)
                    settings = water_db.db_get_water_level_settings(conn)
                    conn.close()
                    full_v = float(settings.get("full_voltage", 0.497))
                    empty_v = float(settings.get("empty_voltage", 2.230))
                    level_percent, status, message = calibration.voltage_to_percent(avg_signal, full_v, empty_v)
                    
                    # DIAGNOSTIC: Non-fatal check if signal is near calibration endpoints
                    # (This is EXPECTED when tank is actually full or empty)
                    if abs(avg_signal - full_v) < 0.02:
                        print(f"[Water Level Live] INFO: Signal voltage {avg_signal:.6f}V is near FULL calibration {full_v:.6f}V (expected when tank is full)")
                    if abs(avg_signal - empty_v) < 0.02:
                        print(f"[Water Level Live] INFO: Signal voltage {avg_signal:.6f}V is near EMPTY calibration {empty_v:.6f}V (expected when tank is empty)")
                    
                    result = {
                        "ok": True,
                        "signal_voltage": avg_signal,  # MUST be raw ADC reading
                        "supply_div_voltage": None,
                        "supply_voltage_est": None,
                        "ratio": None,
                        "level_percent": level_percent,
                        "address": detected_address or "0x48",
                        "status": status,
                        "message": message
                    }
                    # DIAGNOSTIC: Log final JSON response values
                    print(f"[Water Level Live] RESPONSE (no normalization): signal_voltage={result['signal_voltage']:.6f}V, "
                          f"level_percent={result['level_percent']}%, ok={result['ok']}, status={result['status']}")
                
                # Cache result
                _live_read_cache = result
                _live_read_cache_time = now_ts
                return JSONResponse(result)
            else:
                result = {
                    "ok": False,
                    "error": "read_failed",
                    "signal_voltage": None,
                    "supply_div_voltage": None,
                    "supply_voltage_est": None,
                    "ratio": None,
                    "level_percent": None,
                    "address": None,
                    "status": "error",
                    "message": "I2C read error (ADS1115)"
                }
                _live_read_cache = result
                _live_read_cache_time = now_ts
                return JSONResponse(result)
        
        except Exception as e:
            print(f"[API] Error in /api/water/level/live: {e}")
            import traceback
            traceback.print_exc()
            result = {
                "ok": False,
                "error": "internal_error",
                "signal_voltage": None,
                "supply_div_voltage": None,
                "supply_voltage_est": None,
                "ratio": None,
                "level_percent": None,
                "address": None,
                "status": "error",
                "message": f"Internal error: {str(e)}"
            }
            _live_read_cache = result
            _live_read_cache_time = now_ts
            return JSONResponse(result)
    
    @router.get("/level/latest")
    def api_water_level_latest(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        """Get latest water level snapshot. Always HTTP 200."""
        err = require_auth_func(request, x_api_key)
        if err:
            return err
        
        try:
            now = int(time.time())
            conn = sqlite3.connect(db_path)
            snapshot = water_db.db_get_water_level_snapshot(conn)
            conn.close()
            
            if not snapshot:
                return JSONResponse({
                    "ok": True,
                    "level_percent": None,
                    "avg_voltage": None,
                    "status": "unknown",
                    "age_seconds": 0,
                    "message": "No water level data available yet"
                })
            
            updated_at = snapshot.get("updated_at", 0)
            age_seconds = max(0, now - updated_at) if updated_at > 0 else 0
            
            status = snapshot.get("status", "unknown")
            message = snapshot.get("message", "")
            
            # Recompute level_percent from avg_voltage using current calibration (if snapshot has avg_voltage)
            level_percent = snapshot.get("level_percent")
            avg_voltage = snapshot.get("avg_voltage")
            
            if avg_voltage is not None:
                conn = sqlite3.connect(db_path)
                settings = water_db.db_get_water_level_settings(conn)
                conn.close()
                
                # Try ratio calibration first if available
                use_norm = settings.get("use_supply_normalization", True)
                ratio = snapshot.get("ratio")
                
                if use_norm and ratio is not None:
                    full_ratio = settings.get("full_ratio")
                    empty_ratio = settings.get("empty_ratio")
                    if full_ratio is not None and empty_ratio is not None:
                        level_percent, _, _ = calibration.ratio_to_percent(ratio, full_ratio, empty_ratio)
                else:
                    # Fallback to voltage calibration
                    full_v = float(settings.get("full_voltage", 0.497))
                    empty_v = float(settings.get("empty_voltage", 2.230))
                    level_percent, _, _ = calibration.voltage_to_percent(avg_voltage, full_v, empty_v)
            
            return JSONResponse({
                "ok": True,
                "level_percent": int(level_percent) if level_percent is not None else None,
                "avg_voltage": float(avg_voltage) if avg_voltage is not None else None,
                "calibration_full_voltage": float(settings.get("full_voltage", 0.497)) if 'settings' in locals() else 0.497,
                "calibration_empty_voltage": float(settings.get("empty_voltage", 2.230)) if 'settings' in locals() else 2.230,
                "status": status,
                "age_seconds": age_seconds,
                "message": message
            })
        
        except Exception as e:
            print(f"[API] Error in /api/water/level/latest: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse({
                "ok": False,
                "error": "internal_error",
                "level_percent": None,
                "avg_voltage": None,
                "status": "error",
                "age_seconds": 0,
                "message": f"Internal error: {str(e)}"
            })
    
    @router.get("/level/snapshot")
    def api_water_level_snapshot(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        """Get latest water level snapshot (alias for /latest). Always returns JSON."""
        return api_water_level_latest(request, x_api_key)
    
    @router.get("/diagnostics")
    def api_water_diagnostics(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        """Get water level system diagnostics."""
        err = require_auth_func(request, x_api_key)
        if err:
            return err
        
        try:
            # Check SQLite PRAGMA settings
            conn = sqlite3.connect(db_path, timeout=5.0)
            water_db._set_connection_pragmas(conn)
            cur = conn.cursor()
            
            cur.execute("PRAGMA journal_mode")
            journal_mode = cur.fetchone()[0]
            cur.execute("PRAGMA busy_timeout")
            busy_timeout = cur.fetchone()[0]
            cur.execute("PRAGMA synchronous")
            synchronous = cur.fetchone()[0]
            
            # Get current settings
            settings = water_db.db_get_water_level_settings(conn)
            conn.close()
            
            # Try to detect ADS1115
            from . import reader
            detected_addr = None
            for addr in [0x48, 0x49, 0x4A, 0x4B]:
                try:
                    from smartify import ads1115
                    if ads1115.ads_detect(bus=1, addr=addr, retries=1):
                        detected_addr = f"0x{addr:02X}"
                        break
                except:
                    pass
            
            return JSONResponse({
                "ok": True,
                "sqlite": {
                    "journal_mode": journal_mode,
                    "busy_timeout": busy_timeout,
                    "synchronous": synchronous
                },
                "ads1115": {
                    "detected_address": detected_addr,
                    "signal_channel": settings.get("adc_channel_signal", 0),
                    "supply_channel": settings.get("adc_channel_supply", 1)
                },
                "settings": {
                    "use_normalization": settings.get("use_supply_normalization", True),
                    "full_voltage": settings.get("full_voltage"),
                    "empty_voltage": settings.get("empty_voltage")
                }
            })
        except Exception as e:
            print(f"[API] Error in /api/water/diagnostics: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse({
                "ok": False,
                "error": str(e)
            })
    
    return router


def create_router(db_path: Path, require_auth_func, app_state: Optional[Dict[str, Any]] = None) -> APIRouter:
    """
    Create FastAPI router for water level endpoints (legacy function, use init_router instead).
    
    Args:
        db_path: Path to SQLite database
        require_auth_func: Function that checks authentication (returns error response or None)
        app_state: Optional application state dict (for shared cache)
    
    Returns:
        FastAPI router with water level endpoints
    """
    return _create_router(db_path, require_auth_func, app_state)

