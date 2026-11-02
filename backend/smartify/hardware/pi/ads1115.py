"""ADS1115 16-bit ADC over I2C, using smbus2 directly.

The read sequence below is the one proven on the original van build. The ADS1115
multiplexer needs time to settle after switching channels; without the
throwaway conversion, reading A0 and then A1 can return the A0 value twice.

    1. write config for the channel (starts a conversion)
    2. wait ~4 ms for the multiplexer to settle
    3. read and discard the conversion register
    4. write config again to start a fresh conversion
    5. wait at least two conversion periods
    6. read the result
"""

from __future__ import annotations

import threading
import time

from smartify.hardware.base import HardwareError

_REG_CONVERSION = 0x00
_REG_CONFIG = 0x01

_OS_SINGLE = 0x8000
_MODE_SINGLE = 0x0100
_COMPARATOR_DISABLED = 0x0003
_CHANNEL_MUX = {0: 0x4000, 1: 0x5000, 2: 0x6000, 3: 0x7000}

# Full-scale voltage -> PGA register bits
_PGA = {6.144: 0x0000, 4.096: 0x0200, 2.048: 0x0400, 1.024: 0x0600, 0.512: 0x0800, 0.256: 0x0A00}
# Samples per second -> data rate register bits
_DATA_RATE = {
    8: 0x0000,
    16: 0x0020,
    32: 0x0040,
    64: 0x0060,
    128: 0x0080,
    250: 0x00A0,
    475: 0x00C0,
    860: 0x00E0,
}

_RETRIES = 3

# All I2C traffic is serialized: other I2C devices may share the bus.
I2C_LOCK = threading.Lock()


def config_word(channel: int, full_scale: float, sps: int) -> int:
    if channel not in _CHANNEL_MUX:
        raise ValueError(f"ADS1115 channel must be 0-3, got {channel}")
    if full_scale not in _PGA:
        raise ValueError(f"Unsupported full scale {full_scale} V, use one of {sorted(_PGA)}")
    if sps not in _DATA_RATE:
        raise ValueError(f"Unsupported data rate {sps}, use one of {sorted(_DATA_RATE)}")
    return (
        _OS_SINGLE
        | _CHANNEL_MUX[channel]
        | _PGA[full_scale]
        | _MODE_SINGLE
        | _DATA_RATE[sps]
        | _COMPARATOR_DISABLED
    )


def raw_to_voltage(msb: int, lsb: int, full_scale: float) -> float:
    raw = (msb << 8) | lsb
    if raw > 0x7FFF:
        raw -= 0x10000
    return raw * full_scale / 32768.0


class Ads1115Reader:
    def __init__(
        self,
        bus: int = 1,
        address: int = 0x48,
        full_scale: float = 4.096,
        sps: int = 128,
    ) -> None:
        try:
            from smbus2 import SMBus
        except ImportError as exc:  # pragma: no cover - depends on the Pi
            raise HardwareError(
                "ADS1115 support needs the 'pi' extras: pip install 'smartify-kombi[pi]'"
            ) from exc
        self._smbus = SMBus
        self.bus = bus
        self.address = address
        self.full_scale = full_scale
        self.sps = sps

    def read_voltages(self, channels: tuple[int, ...]) -> tuple[float, ...]:
        last_error: Exception | None = None
        for attempt in range(_RETRIES):
            try:
                with I2C_LOCK, self._smbus(self.bus) as i2c:
                    return tuple(self._read_channel(i2c, ch) for ch in channels)
            except OSError as exc:
                last_error = exc
                time.sleep(0.05 + attempt * 0.02)
        raise HardwareError(
            f"ADS1115 at 0x{self.address:02X} on bus {self.bus} not responding: {last_error}"
        )

    def _read_channel(self, i2c, channel: int) -> float:
        config = config_word(channel, self.full_scale, self.sps)
        config_bytes = [(config >> 8) & 0xFF, config & 0xFF]

        i2c.write_i2c_block_data(self.address, _REG_CONFIG, config_bytes)
        time.sleep(0.004)
        try:
            i2c.read_i2c_block_data(self.address, _REG_CONVERSION, 2)
        except OSError:
            pass  # throwaway read, errors here do not matter
        i2c.write_i2c_block_data(self.address, _REG_CONFIG, config_bytes)
        time.sleep(max(0.03, 2.0 / self.sps))
        msb, lsb = i2c.read_i2c_block_data(self.address, _REG_CONVERSION, 2)
        return raw_to_voltage(msb, lsb, self.full_scale)
