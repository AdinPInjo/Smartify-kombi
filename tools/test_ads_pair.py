#!/usr/bin/env python3
"""
Test script to verify ADS1115 dual-channel reads match multimeter readings.

This script uses the SAME backend ads1115.py module to ensure consistency.
Expected readings (full tank):
    A0 (signal) ≈ 0.497V
    A1 (supply divider) ≈ 2.14V
    
The script should never show A0 == A1 when wiring is correct.
"""

import sys
import time
import os

# Add parent directory to path to import smartify.ads1115
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import ads1115
except ImportError:
    print("Error: Could not import ads1115 module")
    print("Make sure you're running from the Smartify-kombi directory")
    sys.exit(1)


def main():
    """Test ADS1115 pair reads repeatedly."""
    print("Testing ADS1115 dual-channel reads (A0 and A1)")
    print("Expected: A0 ≈ 0.497V, A1 ≈ 2.14V (full tank)")
    print("Press Ctrl+C to stop\n")
    
    try:
        # Detect ADS1115
        if not ads1115.ads_detect(bus=1, addr=0x48, retries=1):
            print("Error: ADS1115 not detected at address 0x48")
            print("Trying other addresses...")
            for addr in [0x49, 0x4A, 0x4B]:
                if ads1115.ads_detect(bus=1, addr=addr, retries=1):
                    print(f"Found ADS1115 at 0x{addr:02X}")
                    break
            else:
                print("Error: ADS1115 not found on any address")
                sys.exit(1)
        
        count = 0
        error_count = 0
        mirrored_count = 0
        
        while True:
            count += 1
            
            # Read both channels using the same function as the backend
            v0, v1 = ads1115.ads_read_voltage_pair(
                channel0=0,  # A0
                channel1=1,  # A1
                bus=1,
                addr=0x48,
                pga=4.096,
                sps=128
            )
            
            if v0 is None or v1 is None:
                error_count += 1
                print(f"Read {count}: ERROR - v0={v0}, v1={v1}")
            else:
                diff = abs(v0 - v1)
                if diff < 0.002:  # 2mV threshold
                    mirrored_count += 1
                    status = "⚠️  MIRRORED"
                else:
                    status = "✓"
                
                print(f"Read {count}: {status} A0={v0:.4f}V, A1={v1:.4f}V, diff={diff:.6f}V")
                
                if mirrored_count > 0:
                    print(f"  Warning: {mirrored_count} mirrored readings so far")
            
            time.sleep(0.5)  # 500ms between reads
            
    except KeyboardInterrupt:
        print(f"\n\nTest stopped after {count} reads")
        print(f"Errors: {error_count}")
        print(f"Mirrored readings: {mirrored_count}")
        if count > 0:
            print(f"Success rate: {((count - error_count - mirrored_count) / count * 100):.1f}%")


if __name__ == "__main__":
    main()

