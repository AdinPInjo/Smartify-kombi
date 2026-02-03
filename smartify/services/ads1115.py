"""
ADS1115 helpers for API endpoints.
"""
from fastapi.responses import JSONResponse


def ads1115_read_response(channel: int, bus: int, addr: int, pga: float) -> JSONResponse:
    # Validate channel
    if channel not in (0, 1, 2, 3):
        return JSONResponse({
            "ok": False,
            "error": "invalid_channel",
            "reason": "Channel must be 0-3",
            "channel": channel
        }, status_code=400)

    try:
        # Import ads1115 module (same directory)
        import ads1115
        ads_detect = ads1115.ads_detect
        ads_read_voltage = ads1115.ads_read_voltage
        ads_read_raw_single_ended = ads1115.ads_read_raw_single_ended
    except ImportError as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[API] Error importing ads1115: {e}\n{error_detail}")
        return JSONResponse({
            "ok": False,
            "error": "module_error",
            "reason": f"Failed to import ads1115 module: {e}",
            "channel": channel
        })
    except AttributeError as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[API] Error: ads1115 module missing required functions: {e}\n{error_detail}")
        return JSONResponse({
            "ok": False,
            "error": "module_error",
            "reason": f"ads1115 module missing required functions: {e}",
            "channel": channel
        })

    # Detect ADS1115
    if not ads_detect(bus=bus, addr=addr):
        return JSONResponse({
            "ok": False,
            "error": "ads_not_found",
            "reason": f"ADS1115 not found at address 0x{addr:02X} on bus {bus}",
            "channel": channel,
            "bus": bus,
            "addr": f"0x{addr:02X}"
        })

    # Read voltage
    voltage = ads_read_voltage(channel, bus=bus, addr=addr, pga=pga, sps=128, retries=3)
    raw_value = ads_read_raw_single_ended(channel, bus=bus, addr=addr, pga=pga, sps=128, retries=3)

    if voltage is None or raw_value is None:
        return JSONResponse({
            "ok": False,
            "error": "read_failed",
            "reason": "Failed to read from ADS1115 channel (I/O error or timeout)",
            "channel": channel,
            "bus": bus,
            "addr": f"0x{addr:02X}"
        })

    return JSONResponse({
        "ok": True,
        "channel": channel,
        "voltage": voltage,
        "raw_value": raw_value,
        "pga": pga,
        "bus": bus,
        "addr": f"0x{addr:02X}"
    })


def ads1115_detect_response(bus: int, addr: int) -> JSONResponse:
    try:
        # Import ads1115 module (same directory)
        import ads1115
        ads_detect = ads1115.ads_detect
    except ImportError as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[API] Error importing ads1115: {e}\n{error_detail}")
        return JSONResponse({
            "ok": False,
            "error": "module_error",
            "reason": f"Failed to import ads1115 module: {e}",
            "detected": False,
            "bus": bus,
            "addr": f"0x{addr:02X}"
        })
    except AttributeError as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[API] Error: ads1115 module missing required functions: {e}\n{error_detail}")
        return JSONResponse({
            "ok": False,
            "error": "module_error",
            "reason": f"ads1115 module missing required functions: {e}",
            "detected": False,
            "bus": bus,
            "addr": f"0x{addr:02X}"
        })

    detected = ads_detect(bus=bus, addr=addr)

    return JSONResponse({
        "ok": True,
        "detected": detected,
        "bus": bus,
        "addr": f"0x{addr:02X}"
    })
