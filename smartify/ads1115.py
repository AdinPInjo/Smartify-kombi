"""
ADS1115 ADC reading using smbus2 directly (no Blinka dependencies).

This module provides low-level access to ADS1115 16-bit ADC via I2C.
Designed to work reliably on Raspberry Pi without sudo or BLINKA environment variables.

All I2C access is serialized with a global lock to prevent concurrent access issues.
Uses raw i2c_rdwr transactions with OS bit polling for deterministic reads.
"""

import time
import threading
from typing import Optional, Tuple

try:
    from smbus2 import SMBus, i2c_msg
except ImportError:
    print("[ADS1115] Error: smbus2 not installed. Install with: pip install smbus2")
    SMBus = None
    i2c_msg = None

# Global lock to serialize all I2C access (prevents concurrent reads from interfering)
I2C_LOCK = threading.Lock()


# ADS1115 I2C address (default)
ADS1115_ADDRESS = 0x48

# Register addresses
ADS1115_REG_CONVERSION = 0x00  # Conversion register (read-only)
ADS1115_REG_CONFIG = 0x01      # Config register (read/write)

# Config register fields
# MUX (bits 14-12): Input selection
ADS1115_MUX_AIN0_GND = 0x4000  # AIN0 vs GND (channel 0)
ADS1115_MUX_AIN1_GND = 0x5000  # AIN1 vs GND (channel 1)
ADS1115_MUX_AIN2_GND = 0x6000  # AIN2 vs GND (channel 2)
ADS1115_MUX_AIN3_GND = 0x7000  # AIN3 vs GND (channel 3)

# PGA (bits 11-9): Programmable Gain Amplifier
ADS1115_PGA_6_144V = 0x0000  # ±6.144V
ADS1115_PGA_4_096V = 0x0200  # ±4.096V (default)
ADS1115_PGA_2_048V = 0x0400  # ±2.048V
ADS1115_PGA_1_024V = 0x0600  # ±1.024V
ADS1115_PGA_0_512V = 0x0800  # ±0.512V
ADS1115_PGA_0_256V = 0x0A00  # ±0.256V

# MODE (bit 8): 0 = continuous, 1 = single-shot
ADS1115_MODE_SINGLE = 0x0100  # Single-shot mode

# DR (bits 7-5): Data rate (samples per second)
ADS1115_DR_128SPS = 0x0000    # 128 SPS (default)
ADS1115_DR_250SPS = 0x0020    # 250 SPS
ADS1115_DR_490SPS = 0x0040    # 490 SPS
ADS1115_DR_920SPS = 0x0060    # 920 SPS
ADS1115_DR_1600SPS = 0x0080   # 1600 SPS
ADS1115_DR_2400SPS = 0x00A0   # 2400 SPS
ADS1115_DR_3300SPS = 0x00C0   # 3300 SPS

# OS (bit 15): Operational status / single-shot start
ADS1115_OS_SINGLE = 0x8000    # Start single-shot conversion

# Channel to MUX mapping (single-ended mode: AINx vs GND)
# MUX bits 14-12: 100=AIN0, 101=AIN1, 110=AIN2, 111=AIN3
CHANNEL_MUX = {
    0: ADS1115_MUX_AIN0_GND,  # 0x4000 = 0100 0000 0000 0000
    1: ADS1115_MUX_AIN1_GND,  # 0x5000 = 0101 0000 0000 0000
    2: ADS1115_MUX_AIN2_GND,  # 0x6000 = 0110 0000 0000 0000
    3: ADS1115_MUX_AIN3_GND,  # 0x7000 = 0111 0000 0000 0000
}

# PGA to voltage range mapping (full-scale range)
PGA_VOLTAGE_RANGE = {
    6.144: ADS1115_PGA_6_144V,
    4.096: ADS1115_PGA_4_096V,
    2.048: ADS1115_PGA_2_048V,
    1.024: ADS1115_PGA_1_024V,
    0.512: ADS1115_PGA_0_512V,
    0.256: ADS1115_PGA_0_256V,
}


def _get_pga_value(pga_volts: float) -> int:
    """Convert PGA voltage to register value."""
    # Find closest match
    available = sorted(PGA_VOLTAGE_RANGE.keys())
    closest = min(available, key=lambda x: abs(x - pga_volts))
    return PGA_VOLTAGE_RANGE[closest]


def _get_sps_value(sps: int) -> int:
    """Convert samples per second to register value."""
    sps_map = {
        128: ADS1115_DR_128SPS,
        250: ADS1115_DR_250SPS,
        490: ADS1115_DR_490SPS,
        920: ADS1115_DR_920SPS,
        1600: ADS1115_DR_1600SPS,
        2400: ADS1115_DR_2400SPS,
        3300: ADS1115_DR_3300SPS,
    }
    # Find closest match
    available = sorted(sps_map.keys())
    closest = min(available, key=lambda x: abs(x - sps))
    return sps_map[closest]


# Raw I2C register IO helpers using i2c_rdwr (more deterministic than block operations)
def _write_u16_be(bus: SMBus, addr: int, reg: int, value: int) -> None:
    """
    Write 16-bit value to register in big-endian format.
    
    ADS1115 expects big-endian for 16-bit registers.
    Uses raw i2c_rdwr for deterministic behavior.
    """
    if SMBus is None or i2c_msg is None:
        raise RuntimeError("smbus2 not available")
    # Register pointer + 2 bytes (big-endian)
    data = bytes([reg, (value >> 8) & 0xFF, value & 0xFF])
    msg = i2c_msg.write(addr, data)
    bus.i2c_rdwr(msg)


def _read_u16_be(bus: SMBus, addr: int, reg: int) -> int:
    """
    Read 16-bit value from register (big-endian).
    
    Uses pointer register write followed by data read (standard I2C pattern).
    Uses raw i2c_rdwr for deterministic behavior.
    """
    if SMBus is None or i2c_msg is None:
        raise RuntimeError("smbus2 not available")
    # Write pointer register
    msg_w = i2c_msg.write(addr, bytes([reg]))
    # Read 2 bytes
    msg_r = i2c_msg.read(addr, 2)
    bus.i2c_rdwr(msg_w, msg_r)
    # Convert to unsigned 16-bit (big-endian)
    b = bytes(msg_r)
    if len(b) < 2:
        raise IOError(f"Expected 2 bytes, got {len(b)}")
    return (b[0] << 8) | b[1]


def _build_config(channel: int, pga: float = 4.096, sps: int = 128) -> int:
    """
    Build ADS1115 config register value for single-ended channel read.
    
    Args:
        channel: Channel number (0-3)
        pga: Programmable gain amplifier voltage range (default 4.096V)
        sps: Samples per second (default 128)
    
    Returns:
        16-bit config register value
    """
    mux = CHANNEL_MUX.get(channel)
    if mux is None:
        raise ValueError(f"Invalid channel: {channel}. Must be 0-3.")
    
    pga_value = _get_pga_value(pga)
    sps_value = _get_sps_value(sps)
    
    # Config: OS (start) | MUX | PGA | MODE (single-shot) | DR | COMP_QUE (disable)
    return (
        ADS1115_OS_SINGLE |  # Start single-shot conversion
        mux |                # Channel selection
        pga_value |          # PGA setting
        ADS1115_MODE_SINGLE |  # Single-shot mode
        sps_value |          # Data rate
        0x0003               # Comparator queue (disable)
    )


def ads_detect(bus: int = 1, addr: int = ADS1115_ADDRESS, retries: int = 3) -> bool:
    """
    Detect if ADS1115 is present on I2C bus.
    
    Args:
        bus: I2C bus number (typically 1 on Raspberry Pi)
        addr: I2C address (default 0x48)
        retries: Number of retry attempts
    
    Returns:
        True if ADS1115 is detected, False otherwise
    """
    if SMBus is None:
        return False
    
    for attempt in range(retries):
        try:
            with I2C_LOCK:  # Serialize I2C access
                with SMBus(bus) as i2c_bus:
                    # Try to read from config register (should always be readable)
                    # This is a simple presence check
                    config = _read_u16_be(i2c_bus, addr, ADS1115_REG_CONFIG)
                    if config is not None:
                        return True
        except (OSError, IOError) as e:
            if attempt < retries - 1:
                time.sleep(0.05)  # 50ms delay before retry
                continue
            print(f"[ADS1115] Detection failed after {retries} attempts: {e}")
            return False
        except Exception as e:
            print(f"[ADS1115] Unexpected error during detection: {e}")
            return False
    
    return False


def ads_read_raw_single_ended(
    bus: SMBus,
    addr: int,
    channel: int,
    pga: float = 4.096,
    sps: int = 128,
    timeout_ms: int = 120
) -> Optional[int]:
    """
    Read raw ADC value from a single-ended channel using OS bit polling.
    
    This function performs a deterministic single-shot conversion by:
    1. Writing config register with channel selection and OS bit set
    2. Polling OS bit in config register until conversion completes
    3. Reading conversion register once OS bit is set
    
    Args:
        bus: Open SMBus instance (must be opened and locked externally)
        addr: I2C address (default 0x48)
        channel: Channel number (0-3)
        pga: Programmable gain amplifier voltage range (default 4.096V)
        sps: Samples per second (default 128)
        timeout_ms: Maximum time to wait for conversion (default 120ms)
    
    Returns:
        Raw 16-bit ADC value (-32768 to 32767), or None on error
    """
    if channel not in (0, 1, 2, 3):
        print(f"[ADS1115] Invalid channel: {channel}. Must be 0-3.")
        return None
    
    try:
        # Build config register value
        cfg = _build_config(channel, pga, sps)
        
        # Write config register (this starts the conversion)
        _write_u16_be(bus, addr, ADS1115_REG_CONFIG, cfg)
        
        # Poll OS bit in config register until conversion completes
        # OS bit (bit 15) = 1 means conversion is complete
        t0 = time.time()
        while True:
            c = _read_u16_be(bus, addr, ADS1115_REG_CONFIG)
            if (c & 0x8000) != 0:  # OS bit is set (conversion done)
                break
            elapsed_ms = (time.time() - t0) * 1000
            if elapsed_ms > timeout_ms:
                print(f"[ADS1115] Timeout waiting for conversion on channel {channel}")
                return None
            time.sleep(0.001)  # 1ms polling interval
        
        # Read conversion register (16-bit, big-endian)
        raw = _read_u16_be(bus, addr, ADS1115_REG_CONVERSION)
        
        # Convert unsigned 16-bit to signed 16-bit
        if raw > 32767:
            raw -= 65536
        
        return raw
        
    except Exception as e:
        print(f"[ADS1115] Error reading channel {channel}: {e}")
        return None


def ads_read_voltage(
    channel: int,
    bus: int = 1,
    addr: int = ADS1115_ADDRESS,
    pga: float = 4.096,
    sps: int = 128,
    retries: int = 3
) -> Optional[float]:
    """
    Read voltage from a single-ended channel.
    
    Args:
        channel: Channel number (0-3)
        bus: I2C bus number (typically 1 on Raspberry Pi)
        addr: I2C address (default 0x48)
        pga: Programmable gain amplifier voltage range (default 4.096V)
        sps: Samples per second (default 128)
        retries: Number of retry attempts on I/O error
    
    Returns:
        Voltage in volts, or None on error
    """
    if SMBus is None:
        return None
    
    for attempt in range(retries):
        try:
            with I2C_LOCK:
                with SMBus(bus) as i2c_bus:
                    raw = ads_read_raw_single_ended(i2c_bus, addr, channel, pga, sps)
                    if raw is not None:
                        # Convert raw value to voltage
                        voltage = (raw / 32767.0) * pga
                        return voltage
        except (OSError, IOError) as e:
            if attempt < retries - 1:
                delay = 0.05 + (attempt * 0.02)  # 50ms, 70ms, 90ms
                time.sleep(delay)
                continue
            print(f"[ADS1115] I/O error reading channel {channel} after {retries} attempts: {e}")
            return None
        except Exception as e:
            print(f"[ADS1115] Unexpected error reading channel {channel}: {e}")
            return None
    
    return None


def ads_read_voltage_pair(
    channel0: int,
    channel1: int,
    bus: int = 1,
    addr: int = ADS1115_ADDRESS,
    pga: float = 4.096,
    sps: int = 128
) -> Tuple[Optional[float], Optional[float]]:
    """
    Read voltages from two single-ended channels in one SMBus session.
    
    This function opens a single SMBus connection and reads both channels sequentially.
    Uses priming reads (discard first read per channel) to ensure proper MUX switching,
    then performs OS-bit-polled reads for deterministic results.
    
    IMPORTANT: After changing MUX, the first conversion can still be from the previous channel.
    To be safe, we do one "priming" read per channel (discard), then read again.
    
    Args:
        channel0: First channel number (0-3)
        channel1: Second channel number (0-3)
        bus: I2C bus number (typically 1 on Raspberry Pi)
        addr: I2C address (default 0x48)
        pga: Programmable gain amplifier voltage range (default 4.096V)
        sps: Samples per second (default 128)
    
    Returns:
        Tuple of (voltage0, voltage1) in volts, or (None, None) on error
        Each voltage may be None if that specific channel read failed
    """
    if channel0 not in (0, 1, 2, 3) or channel1 not in (0, 1, 2, 3):
        print(f"[ADS1115] Invalid channels: {channel0}, {channel1}. Must be 0-3.")
        return (None, None)
    
    if channel0 == channel1:
        raise ValueError("Channels must differ")
    
    if SMBus is None:
        return (None, None)
    
    try:
        with I2C_LOCK:  # Serialize I2C access - both channels read in one critical section
            with SMBus(bus) as i2c_bus:
                # Important: after changing mux, first conversion can still be previous channel.
                # To be extra safe: do one "priming" read per channel (discard), then read again.
                
                # Prime channel0 (discard first read)
                _ = ads_read_raw_single_ended(i2c_bus, addr, channel0, pga, sps)
                # Actual read for channel0
                r0 = ads_read_raw_single_ended(i2c_bus, addr, channel0, pga, sps)
                
                # Prime channel1 (discard first read)
                _ = ads_read_raw_single_ended(i2c_bus, addr, channel1, pga, sps)
                # Actual read for channel1
                r1 = ads_read_raw_single_ended(i2c_bus, addr, channel1, pga, sps)
        
        if r0 is None or r1 is None:
            return (None, None)
        
        # Convert raw values to voltages
        v0 = (r0 / 32767.0) * pga
        v1 = (r1 / 32767.0) * pga
        
        return (v0, v1)
        
    except Exception as e:
        print(f"[ADS1115] Error reading channel pair ({channel0}, {channel1}): {e}")
        return (None, None)
