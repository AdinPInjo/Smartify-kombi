"""Water level ADS1115 reader (the only place that touches ADS1115 hardware)."""

from typing import Optional, Tuple

# Use absolute import to ensure it works under systemd
try:
    from smartify import ads1115
except ImportError as e:
    print(f"[Water Level Reader] CRITICAL: Failed to import ads1115 module: {e}")
    import traceback
    traceback.print_exc()
    ads1115 = None


def read_ads_pair(
    signal_ch: int,
    supply_ch: int,
    *,
    addr_candidates: Optional[list] = None,
    bus: int = 1,
    pga: float = 4.096,
    sps: int = 128
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Read voltages from two ADS1115 channels (signal and supply).
    
    This is the ONLY function that touches ADS1115 hardware.
    Uses smartify/ads1115.py library functions.
    
    Args:
        signal_ch: Signal channel number (0-3)
        supply_ch: Supply channel number (0-3)
        addr_candidates: List of I2C addresses to try (default: [0x48, 0x49, 0x4A, 0x4B])
        bus: I2C bus number (default: 1)
        pga: Programmable gain amplifier voltage range (default: 4.096V)
        sps: Samples per second (default: 128)
    
    Returns:
        Tuple of (signal_voltage, supply_div_voltage, detected_address)
        - signal_voltage: Voltage on signal channel (A0), or None on error
        - supply_div_voltage: Voltage on supply divider channel (A1), or None on error
        - detected_address: Detected I2C address as string (e.g., "0x48"), or None
    """
    if ads1115 is None:
        print("[Water Level Reader] Error: ads1115 module not available (import failed at module load)")
        return (None, None, None)
    
    if addr_candidates is None:
        addr_candidates = [0x48, 0x49, 0x4A, 0x4B]
    
    for addr in addr_candidates:
        try:
            # Detect ADS1115
            if not ads1115.ads_detect(bus=bus, addr=addr, retries=1):
                continue
            
            # Read voltage pair from channels
            # ads_read_voltage_pair should handle retries internally
            v0, v1 = ads1115.ads_read_voltage_pair(
                ch0=signal_ch,
                ch1=supply_ch,
                bus=bus,
                addr=addr,
                pga=pga,
                sps=sps
            )
            
            if v0 is not None or v1 is not None:
                return (v0, v1, f"0x{addr:02X}")
        except Exception as e:
            print(f"[Water Level Reader] Error reading from address 0x{addr:02X}: {e}")
            continue
    
    # No ADS1115 found or all reads failed
    return (None, None, None)

