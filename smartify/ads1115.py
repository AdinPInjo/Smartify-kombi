"""
ADS1115 ADC reading using smbus2 directly (no Blinka dependencies).

This module provides low-level access to ADS1115 16-bit ADC via I2C.
Designed to work reliably on Raspberry Pi without sudo or BLINKA environment variables.

All I2C access is serialized with a global lock to prevent concurrent access issues.
Uses stable smbus2 block operations (write_i2c_block_data/read_i2c_block_data).
"""

import time
import threading
from typing import Optional, Tuple

try:
    from smbus2 import SMBus
except ImportError:
    print("[ADS1115] Error: smbus2 not installed. Install with: pip install smbus2")
    SMBus = None

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
# ADS1115-specific values (NOT ADS1015)
ADS1115_DR_8SPS   = 0x0000  # 8 SPS
ADS1115_DR_16SPS  = 0x0020  # 16 SPS
ADS1115_DR_32SPS  = 0x0040  # 32 SPS
ADS1115_DR_64SPS  = 0x0060  # 64 SPS
ADS1115_DR_128SPS = 0x0080  # 128 SPS (CORRECTED - was 0x0000!)
ADS1115_DR_250SPS = 0x00A0  # 250 SPS
ADS1115_DR_475SPS = 0x00C0  # 475 SPS
ADS1115_DR_860SPS = 0x00E0  # 860 SPS

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
    available = sorted(PGA_VOLTAGE_RANGE.keys())
    closest = min(available, key=lambda x: abs(x - pga_volts))
    return PGA_VOLTAGE_RANGE[closest]


def _get_sps_value(sps: int) -> int:
    """
    Get the SPS (samples per second) register value for ADS1115.
    
    Valid values: 8, 16, 32, 64, 128, 250, 475, 860
    Default: 128 SPS (0x0080)
    """
    sps_map = {
        8: ADS1115_DR_8SPS,      # 0x0000
        16: ADS1115_DR_16SPS,    # 0x0020
        32: ADS1115_DR_32SPS,    # 0x0040
        64: ADS1115_DR_64SPS,    # 0x0060
        128: ADS1115_DR_128SPS,  # 0x0080 (CORRECTED)
        250: ADS1115_DR_250SPS,  # 0x00A0
        475: ADS1115_DR_475SPS,  # 0x00C0
        860: ADS1115_DR_860SPS,  # 0x00E0
    }
    return sps_map.get(sps, ADS1115_DR_128SPS)  # Default to 128 SPS


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
                with SMBus(bus) as i2c:
                    # Try to read from config register (should always be readable)
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
    
    Uses a proven pattern to ensure proper MUX switching:
    1. Write config for target channel
    2. Sleep 3-5ms for MUX to settle
    3. Perform one throwaway conversion read (discard)
    4. Trigger fresh conversion
    5. Sleep max(0.03, 2*(1/sps)) for conversion
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
    
    if SMBus is None:
        return None
    
    # Build config register value
    mux = CHANNEL_MUX[channel]
    pga_value = _get_pga_value(pga)
    sps_value = _get_sps_value(sps)
    
    # Config: OS (start) | MUX | PGA | MODE (single-shot) | DR | COMP_QUE (disable)
    config = (
        ADS1115_OS_SINGLE |  # Start single-shot conversion
        mux |                # Channel selection
        pga_value |          # PGA setting
        ADS1115_MODE_SINGLE |  # Single-shot mode
        sps_value |          # Data rate
        0x0003               # Comparator queue (disable)
    )
    
    for attempt in range(retries):
        try:
            with I2C_LOCK:  # Serialize I2C access
                with SMBus(bus) as i2c:
                    # Step 1: Write config register to set channel and start conversion
                    config_bytes = [(config >> 8) & 0xFF, config & 0xFF]  # Big-endian
                    i2c.write_i2c_block_data(addr, ADS1115_REG_CONFIG, config_bytes)
                    
                    # Step 2: Wait 3-5ms for MUX to settle
                    time.sleep(0.004)  # 4ms settle time
                    
                    # Step 3: Read conversion once and discard (throwaway to clear stale data)
                    try:
                        _ = i2c.read_i2c_block_data(addr, ADS1115_REG_CONVERSION, 2)
                    except:
                        pass  # Ignore errors on throwaway read
                    
                    # Step 4: Trigger a fresh conversion by writing config again
                    i2c.write_i2c_block_data(addr, ADS1115_REG_CONFIG, config_bytes)
                    
                    # Step 5: Wait for conversion to complete: max(0.03, 2*(1/sps))
                    conversion_time = 1.0 / sps
                    sleep_time = max(0.03, 2 * conversion_time)
                    time.sleep(sleep_time)
                    
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
    # ADS1115 is 16-bit signed: range is -32768 to +32767
    # Voltage = raw_value * (pga_voltage / 32768.0)
    voltage = raw * (pga / 32768.0)
    return voltage


def _read_raw_with_smbus(
    i2c,
    addr: int,
    channel: int,
    pga: float,
    sps: int
) -> Optional[int]:
    """
    Helper: Read raw ADC value using the proven 6-step pattern from ads_read_raw_single_ended.
    
    This function performs the exact same sequence as ads_read_raw_single_ended, but accepts
    an existing SMBus instance so it can be called multiple times within one session.
    
    Args:
        i2c: Active SMBus instance
        addr: I2C address
        channel: Channel number (0-3)
        pga: PGA voltage range
        sps: Samples per second
    
    Returns:
        Raw 16-bit signed ADC value, or None on error
    """
    if channel not in (0, 1, 2, 3):
        print(f"[ADS1115] Invalid channel: {channel}. Must be 0-3.")
        return None
    
    mux = CHANNEL_MUX[channel]
    pga_value = _get_pga_value(pga)
    sps_value = _get_sps_value(sps)
    
    # Config: OS (start) | MUX | PGA | MODE (single-shot) | DR | COMP_QUE (disable)
    config = (
        ADS1115_OS_SINGLE |  # Start single-shot conversion
        mux |                # Channel selection
        pga_value |          # PGA setting
        ADS1115_MODE_SINGLE |  # Single-shot mode
        sps_value |          # Data rate
        0x0003               # Comparator queue (disable)
    )
    
    try:
        # Step 1: Write config register to set channel and start conversion
        config_bytes = [(config >> 8) & 0xFF, config & 0xFF]  # Big-endian
        i2c.write_i2c_block_data(addr, ADS1115_REG_CONFIG, config_bytes)
        
        # Step 2: Wait 3-5ms for MUX to settle
        time.sleep(0.004)  # 4ms settle time
        
        # Step 3: Read conversion once and discard (throwaway to clear stale data)
        try:
            _ = i2c.read_i2c_block_data(addr, ADS1115_REG_CONVERSION, 2)
        except:
            pass  # Ignore errors on throwaway read
        
        # Step 4: Trigger a fresh conversion by writing config again
        i2c.write_i2c_block_data(addr, ADS1115_REG_CONFIG, config_bytes)
        
        # Step 5: Wait for conversion to complete: max(0.03, 2*(1/sps))
        conversion_time = 1.0 / sps
        sleep_time = max(0.03, 2 * conversion_time)
        time.sleep(sleep_time)
        
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
            
    except Exception as e:
        print(f"[ADS1115] Error in _read_raw_with_smbus for channel {channel}: {e}")
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
    
    Uses the same proven 6-step pattern as ads_read_raw_single_ended for each channel.
    Both channels are read within a single I2C_LOCK critical section.
    
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
        print(f"[ADS1115] Error: Channels must differ (got {channel0} and {channel1})")
        return (None, None)
    
    if SMBus is None:
        return (None, None)
    
    # Retry entire pair read up to 3 times on I/O errors
    for attempt in range(3):
        try:
            with I2C_LOCK:  # Serialize I2C access - both channels read in one critical section
                with SMBus(bus) as i2c:
                    voltages = [None, None]
                    channels = [channel0, channel1]
                    
                    for idx, ch in enumerate(channels):
                        # Use the same 6-step pattern as ads_read_raw_single_ended
                        raw_value = _read_raw_with_smbus(i2c, addr, ch, pga, sps)
                        
                        if raw_value is not None:
                            # Convert raw value to voltage
                            # ADS1115 is 16-bit signed: range is -32768 to +32767
                            voltage = raw_value * (pga / 32768.0)
                            voltages[idx] = voltage
                            print(f"[ADS1115] Channel {ch}: raw={raw_value}, voltage={voltage:.6f}V")
                        else:
                            print(f"[ADS1115] Channel {ch}: read failed (None)")
                            voltages[idx] = None
                    
                    # Verify channels are distinct
                    if voltages[0] is not None and voltages[1] is not None:
                        diff = abs(voltages[0] - voltages[1])
                        if diff < 0.001:
                            print(f"[ADS1115] WARNING: Channels {channel0} and {channel1} returned same value: {voltages[0]:.6f}V")
                    
                    # Return both voltages (may be None if read failed)
                    return (voltages[0], voltages[1])
                    
        except (OSError, IOError) as e:
            if attempt < 2:  # Retry up to 3 times (0, 1, 2)
                delay = 0.05 + (attempt * 0.05)  # 50ms, 100ms, 150ms backoff
                time.sleep(delay)
                continue
            print(f"[ADS1115] I/O error reading channel pair ({channel0}, {channel1}) after 3 attempts: {e}")
            return (None, None)
        except Exception as e:
            print(f"[ADS1115] Unexpected error reading channel pair ({channel0}, {channel1}): {e}")
            import traceback
            traceback.print_exc()
            return (None, None)
    
    return (None, None)
