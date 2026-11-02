#!/usr/bin/env python3
"""
Test script to verify ADS1115 pair reading using the same library functions as the backend.
Run from repo root: python3 smartify/tools/test_ads_pair.py
"""

import sys
import time
from pathlib import Path

# Add repo root to path if needed
repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Use absolute import (same as backend)
from smartify import ads1115

def main():
    print("=== ADS1115 Pair Read Test ===")
    print("Using the same ads1115.py library as the backend service")
    print()
    
    # Configuration (same as water level defaults)
    bus = 1
    pga = 4.096
    sps = 128
    addr_candidates = [0x48, 0x49, 0x4A, 0x4B]
    channel_a0 = 0
    channel_a1 = 1
    
    # Detect ADS1115
    print("Detecting ADS1115...")
    detected_addr = None
    for addr in addr_candidates:
        try:
            if ads1115.ads_detect(addr=addr, bus=bus):
                detected_addr = addr
                print(f"✓ ADS1115 detected at 0x{addr:02X}")
                break
        except Exception as e:
            print(f"  0x{addr:02X}: {e}")
    
    if not detected_addr:
        print("✗ No ADS1115 found on any address")
        return 1
    
    print()
    print(f"Reading A{channel_a0} and A{channel_a1} every 2 seconds...")
    print(f"PGA={pga}V, SPS={sps}, Bus={bus}")
    print()
    print("Sample  |      A0 (V)  |      A1 (V)  |   Diff (V)  | Ratio")
    print("--------|--------------|--------------|-------------|-------")
    
    sample_num = 0
    try:
        while True:
            sample_num += 1
            
            # Read both channels using the library function
            v0, v1 = ads1115.ads_read_voltage_pair(
                channel0=channel_a0,
                channel1=channel_a1,
                addr=detected_addr,
                bus=bus,
                pga=pga,
                sps=sps
            )
            
            if v0 is not None and v1 is not None:
                diff = abs(v0 - v1)
                ratio = v0 / v1 if v1 > 0 else float('inf')
                status = "⚠ MIRRORED" if diff < 0.01 else "✓"
                print(f"{sample_num:6d}  | {v0:10.6f}V  | {v1:10.6f}V  | {diff:9.6f}V  | {ratio:5.3f} {status}")
            else:
                print(f"{sample_num:6d}  | {'ERROR':>10}   | {'ERROR':>10}   | {'---':>9}   | ---")
            
            time.sleep(2)
    
    except KeyboardInterrupt:
        print()
        print("✓ Test stopped by user")
        return 0
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())

