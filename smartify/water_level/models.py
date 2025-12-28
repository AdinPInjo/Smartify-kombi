"""Water level data models (typed dicts)."""

from typing import Optional, Dict, Any, TypedDict


class WaterLevelSettings(TypedDict, total=False):
    """Water level calibration settings."""
    id: str
    full_voltage: float
    empty_voltage: float
    use_supply_normalization: bool
    adc_channel_signal: int
    adc_channel_supply: int
    divider_r_top: float
    divider_r_bottom: float
    full_ratio: Optional[float]
    empty_ratio: Optional[float]
    full_supply_voltage: Optional[float]
    empty_supply_voltage: Optional[float]
    updated_at: int


class WaterLevelLiveReading(TypedDict, total=False):
    """Live water level reading from ADS1115."""
    ok: bool
    signal_voltage: Optional[float]
    supply_div_voltage: Optional[float]
    supply_voltage_est: Optional[float]
    ratio: Optional[float]
    level_percent: Optional[int]
    address: Optional[str]
    status: str
    message: str
    error: Optional[str]


class WaterLevelSnapshot(TypedDict, total=False):
    """Water level snapshot stored in database."""
    id: int
    avg_voltage: float
    level_percent: int
    status: str
    message: str
    updated_at: int
    created_at: int
    avg_signal_voltage: Optional[float]
    avg_supply_div_voltage: Optional[float]
    supply_voltage_est: Optional[float]
    ratio: Optional[float]

