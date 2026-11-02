#!/usr/bin/env python3
"""
Test script for ADS1115 using smbus2 directly.

This script tests ADS1115 detection and reads voltages from all channels (A0-A3).
No dependencies except smbus2.

Usage:
    python tools/test_ads_smbus2.py
"""

import sys
import os

# Add parent directory to path to import ads1115 module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from smartify.ads1115 import ads_detect, ads_read_voltage
except ImportError as e:
    print(f"Error importing ads1115: {e}")
    print("Make sure you're running from the project root directory.")
    sys.exit(1)


def main():
    """Test ADS1115 detection and reading."""
    bus = 1
    addr = 0x48
    
    print(f"Testing ADS1115 on I2C bus {bus}, address 0x{addr:02X}...")
    print()
    
    # Test detection
    print("1. Detecting ADS1115...")
    if ads_detect(bus=bus, addr=addr):
        print(f"   ✓ ADS1115 found at address 0x{addr:02X}")
    else:
        print(f"   ✗ ADS1115 not found at address 0x{addr:02X}")
        print()
        print("Troubleshooting:")
        print("  - Check I2C connection: i2cdetect -y 1")
        print("  - Ensure user is in i2c group: groups")
        print("  - Check /dev/i2c-1 permissions: ls -l /dev/i2c-1")
        print("  - If needed, add user to i2c group: sudo usermod -a -G i2c $USER")
        sys.exit(1)
    
    print()
    print("2. Reading voltages from all channels (A0-A3)...")
    print("   Channel | Voltage (V)")
    print("   ------- | -----------")
    
    for channel in range(4):
        voltage = ads_read_voltage(channel, bus=bus, addr=addr, pga=4.096, sps=128)
        if voltage is not None:
            print(f"   A{channel}     | {voltage:8.4f} V")
        else:
            print(f"   A{channel}     | ERROR")
    
    print()
    print("Test complete.")


if __name__ == "__main__":
    main()

