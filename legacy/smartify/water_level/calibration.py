"""Water level calibration functions (pure functions)."""

from typing import Optional, Tuple


def voltage_to_percent(
    voltage: float,
    full_v: float,
    empty_v: float
) -> Tuple[int, str, str]:
    """
    Convert voltage to water level percent using linear calibration.
    
    Args:
        voltage: Voltage reading in volts
        full_v: Full tank voltage
        empty_v: Empty tank voltage
    
    Returns:
        Tuple of (level_percent, status, message)
        - level_percent: Integer 0-100
        - status: "ok", "error"
        - message: Human-readable status message
    """
    # Validate calibration
    EPSILON = 0.001  # Minimum voltage difference
    if full_v <= 0 or empty_v <= 0:
        return (0, "error", "Invalid calibration settings (voltages must be positive)")
    
    if abs(full_v - empty_v) < EPSILON:
        return (0, "error", "Invalid calibration settings (full and empty voltages too close)")
    
    # Determine which direction: if full_v < empty_v, it's inverted (lower voltage = higher level)
    # If full_v > empty_v, it's normal (higher voltage = higher level)
    
    # Clamp to calibration range
    if full_v < empty_v:
        # Inverted mapping (lower voltage = higher level)
        if voltage <= full_v:
            percent = 100
        elif voltage >= empty_v:
            percent = 0
        else:
            # Linear interpolation
            voltage_range = empty_v - full_v
            percent = 100.0 * (empty_v - voltage) / voltage_range
            percent = max(0, min(100, percent))  # Clamp to 0-100
    else:
        # Normal mapping (higher voltage = higher level)
        if voltage >= full_v:
            percent = 100
        elif voltage <= empty_v:
            percent = 0
        else:
            # Linear interpolation
            voltage_range = full_v - empty_v
            percent = 100.0 * (voltage - empty_v) / voltage_range
            percent = max(0, min(100, percent))  # Clamp to 0-100
    
    return (int(round(percent)), "ok", "Reading stable")


def ratio_to_percent(
    ratio: float,
    full_ratio: float,
    empty_ratio: float
) -> Tuple[int, str, str]:
    """
    Convert signal/supply ratio to water level percent using linear calibration.
    
    Args:
        ratio: Signal voltage / Supply voltage ratio
        full_ratio: Full tank ratio
        empty_ratio: Empty tank ratio
    
    Returns:
        Tuple of (level_percent, status, message)
        - level_percent: Integer 0-100
        - status: "ok", "error"
        - message: Human-readable status message
    """
    # Validate calibration
    EPSILON = 0.0001  # Minimum ratio difference
    if full_ratio <= 0 or empty_ratio <= 0:
        return (0, "error", "Invalid calibration settings (ratios must be positive)")
    
    if abs(full_ratio - empty_ratio) < EPSILON:
        return (0, "error", "Invalid calibration settings (full and empty ratios too close)")
    
    # Determine which direction: if full_ratio < empty_ratio, it's inverted (lower ratio = higher level)
    # If full_ratio > empty_ratio, it's normal (higher ratio = higher level)
    
    # Clamp to calibration range and compute percent
    if full_ratio < empty_ratio:
        # Inverted mapping: full_ratio (lower value) = 100%, empty_ratio (higher value) = 0%
        # Formula: percent = (empty_ratio - ratio) / (empty_ratio - full_ratio) * 100
        if ratio <= full_ratio:
            percent = 100
        elif ratio >= empty_ratio:
            percent = 0
        else:
            # Linear interpolation: (empty - ratio) / (empty - full) * 100
            ratio_range = empty_ratio - full_ratio
            percent = 100.0 * (empty_ratio - ratio) / ratio_range
            percent = max(0, min(100, percent))  # Clamp to 0-100
    else:
        # Normal mapping: full_ratio (higher value) = 100%, empty_ratio (lower value) = 0%
        # Formula: percent = (ratio - empty_ratio) / (full_ratio - empty_ratio) * 100
        if ratio >= full_ratio:
            percent = 100
        elif ratio <= empty_ratio:
            percent = 0
        else:
            # Linear interpolation: (ratio - empty) / (full - empty) * 100
            ratio_range = full_ratio - empty_ratio
            percent = 100.0 * (ratio - empty_ratio) / ratio_range
            percent = max(0, min(100, percent))  # Clamp to 0-100
    
    return (int(round(percent)), "ok", "Reading stable")


def compute_ratio(signal_v: float, supply_est_v: float) -> float:
    """
    Compute ratio = signal_voltage / supply_voltage_est.
    
    Args:
        signal_v: Signal voltage (A0)
        supply_est_v: Estimated supply voltage (computed from divider)
    
    Returns:
        Ratio value (typically 0.03-0.4)
    """
    if supply_est_v > 0:
        return signal_v / supply_est_v
    return 0.0


def validate_ratio_values(full_ratio: float, empty_ratio: float, use_normalization: bool) -> Optional[str]:
    """
    Validate ratio calibration values.
    
    Args:
        full_ratio: Full tank ratio value
        empty_ratio: Empty tank ratio value
        use_normalization: Whether normalization is enabled
    
    Returns:
        Error message if invalid, None if valid
    """
    if not use_normalization:
        return None  # No validation needed if normalization disabled
    
    # Ratios must be < 1.0 (typical range 0.03-0.4)
    if full_ratio > 1.0 or empty_ratio > 1.0:
        return f"Ratio values must be less than 1.0 (got full_ratio={full_ratio}, empty_ratio={empty_ratio}). Ratios are typically 0.03-0.4. Use 'Set from live' button which saves the correct ratio."
    
    EPSILON = 0.0001
    if full_ratio <= 0 or empty_ratio <= 0:
        return "Ratios must be positive numbers"
    
    if abs(full_ratio - empty_ratio) < EPSILON:
        return "Full and empty ratios must be different"
    
    return None  # Valid

