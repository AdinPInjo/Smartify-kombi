"""
ADS1115 ADC reading using smbus2 directly (no Blinka dependencies).

This module provides low-level access to ADS1115 16-bit ADC via I2C.
Designed to work reliably on Raspberry Pi without sudo or BLINKA environment variables.
"""

import time
from typing import Optional, Tuple


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
    try:
        from smbus2 import SMBus
    except ImportError:
        print("[ADS1115] Error: smbus2 not installed. Install with: pip install smbus2")
        return False
    
    for attempt in range(retries):
        try:
            with SMBus(bus) as i2c:
                # Try to read from config register (should always be readable)
                # This is a simple presence check
                config = i2c.read_i2c_block_data(addr, ADS1115_REG_CONFIG, 2)
                if config is not None and len(config) >= 2:
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
    channel: int,
    bus: int = 1,
    addr: int = ADS1115_ADDRESS,
    pga: float = 4.096,
    sps: int = 128,
    retries: int = 3
) -> Optional[int]:
    """
    Read raw ADC value from a single-ended channel with robust channel switching.
    
    Uses a throwaway read pattern to ensure proper MUX switching:
    1. Write config for target channel
    2. Wait 3-5ms for MUX to settle
    3. Perform one throwaway conversion read (discard)
    4. Trigger fresh conversion
    5. Wait for conversion time
    6. Read final conversion value
    
    Args:
        channel: Channel number (0-3)
        bus: I2C bus number (typically 1 on Raspberry Pi)
        addr: I2C address (default 0x48)
        pga: Programmable gain amplifier voltage range (default 4.096V)
        sps: Samples per second (default 128)
        retries: Number of retry attempts on I/O error
    
    Returns:
        Raw 16-bit ADC value (-32768 to 32767), or None on error
    """
    if channel not in (0, 1, 2, 3):
        print(f"[ADS1115] Invalid channel: {channel}. Must be 0-3.")
        return None
    
    try:
        from smbus2 import SMBus
    except ImportError:
        print("[ADS1115] Error: smbus2 not installed")
        return None
    
    # Build config register value
    mux = CHANNEL_MUX[channel]
    pga_value = _get_pga_value(pga)
    sps_value = _get_sps_value(sps)
    
    # Config: OS (start) | MUX | PGA | MODE (single-shot) | DR | COMP_QUE (disable)
    config = (
        ADS1115_OS_SINGLE |  # Start single-shot conversion
        mux |                # Channel selection (verified: 0x4000, 0x5000, 0x6000, 0x7000)
        pga_value |          # PGA setting
        ADS1115_MODE_SINGLE |  # Single-shot mode
        sps_value |          # Data rate
        0x0003               # Comparator queue (disable)
    )
    
    for attempt in range(retries):
        try:
            with SMBus(bus) as i2c:
                # Step 1: Write config register to set channel and start conversion
                config_bytes = [(config >> 8) & 0xFF, config & 0xFF]  # Big-endian
                i2c.write_i2c_block_data(addr, ADS1115_REG_CONFIG, config_bytes)
                
                # Step 2: Wait 3-5ms for MUX to switch
                time.sleep(0.004)  # 4ms settle time
                
                # Step 3: Read conversion once and discard (throwaway to clear stale data)
                try:
                    _ = i2c.read_i2c_block_data(addr, ADS1115_REG_CONVERSION, 2)
                except:
                    pass  # Ignore errors on throwaway read
                
                # Step 4: Trigger a fresh conversion by writing config again
                i2c.write_i2c_block_data(addr, ADS1115_REG_CONFIG, config_bytes)
                
                # Step 5: Wait for conversion to complete (worst case: 1/sps seconds + margin)
                # For 128 SPS: ~8ms per sample, wait 25ms to be safe
                conversion_time = 1.0 / sps
                time.sleep(max(0.025, conversion_time * 2))  # At least 25ms, or 2x conversion time
                
                # Step 6: Read conversion register (16-bit, big-endian) - this is the value we use
                data = i2c.read_i2c_block_data(addr, ADS1115_REG_CONVERSION, 2)
                if len(data) >= 2:
                    # Convert from big-endian to signed 16-bit integer
                    raw_value = (data[0] << 8) | data[1]
                    # Convert unsigned 16-bit to signed 16-bit
                    if raw_value > 32767:
                        raw_value = raw_value - 65536
                    return raw_value
                else:
                    print(f"[ADS1115] Invalid response length: {len(data)}")
                    return None
                    
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
    raw = ads_read_raw_single_ended(channel, bus, addr, pga, sps, retries)
    if raw is None:
        return None
    
    # Convert raw value to voltage
    # ADS1115 is 16-bit, so max value is 32767 for positive voltages
    # Voltage = (raw_value / 32767) * pga_voltage
    voltage = (raw / 32767.0) * pga
    return voltage

