#!/usr/bin/env python3
"""
Verification script for water level diagnostic logging.
Run this on the Raspberry Pi after deploying the fixes.
"""

import sys
import time
import requests
import json

API_BASE = "http://127.0.0.1:8000"
API_KEY = "your-api-key-here"  # Replace with actual key or remove if auth disabled

def check_startup_logs():
    """Check that ads1115 module loaded correctly"""
    print("=" * 60)
    print("1. CHECKING STARTUP LOGS")
    print("=" * 60)
    import subprocess
    result = subprocess.run(
        ["journalctl", "-u", "smartify-dashboard.service", "-n", "100", "--no-pager"],
        capture_output=True,
        text=True
    )
    
    startup_lines = [line for line in result.stdout.split('\n') if 'Startup' in line and 'ads1115' in line]
    
    if startup_lines:
        print("✅ Found startup log:")
        for line in startup_lines[-1:]:  # Show last one
            print(f"   {line}")
    else:
        print("⚠️  No startup log found for ads1115 module")
    
    print()

def check_live_endpoint():
    """Check /api/water/level/live response and logs"""
    print("=" * 60)
    print("2. TESTING /api/water/level/live")
    print("=" * 60)
    
    headers = {"X-API-Key": API_KEY} if API_KEY != "your-api-key-here" else {}
    
    try:
        response = requests.get(f"{API_BASE}/api/water/level/live", headers=headers, timeout=5)
        data = response.json()
        
        print(f"HTTP Status: {response.status_code}")
        print(f"Response JSON:")
        print(json.dumps(data, indent=2))
        print()
        
        # Verify fields
        signal_v = data.get("signal_voltage")
        supply_v = data.get("supply_div_voltage")
        ratio = data.get("ratio")
        level = data.get("level_percent")
        status = data.get("status")
        ok = data.get("ok")
        
        print("VERIFICATION:")
        
        # Check signal_voltage is present and reasonable
        if signal_v is not None:
            if 0.4 < signal_v < 2.5:
                print(f"✅ signal_voltage = {signal_v:.6f}V (reasonable range)")
            else:
                print(f"⚠️  signal_voltage = {signal_v:.6f}V (unexpected range)")
            
            # Check it's not a calibration value
            if abs(signal_v - 0.497) < 0.001:
                print(f"❌ BUG: signal_voltage = {signal_v:.6f}V matches full_voltage calibration!")
            elif abs(signal_v - 2.230) < 0.001:
                print(f"❌ BUG: signal_voltage = {signal_v:.6f}V matches empty_voltage calibration!")
            else:
                print(f"✅ signal_voltage is not a calibration value")
        else:
            print(f"⚠️  signal_voltage is None")
        
        # Check supply voltage if present
        if supply_v is not None:
            if 1.5 < supply_v < 3.0:
                print(f"✅ supply_div_voltage = {supply_v:.6f}V (reasonable range)")
            else:
                print(f"⚠️  supply_div_voltage = {supply_v:.6f}V (unexpected range)")
            
            # Check channels are distinct
            if signal_v is not None:
                diff = abs(signal_v - supply_v)
                if diff > 0.5:
                    print(f"✅ Channels are distinct (diff = {diff:.6f}V)")
                else:
                    print(f"⚠️  Channels appear similar (diff = {diff:.6f}V)")
        
        # Check ratio
        if ratio is not None:
            if 0.0 <= ratio <= 1.0:
                print(f"✅ ratio = {ratio:.4f} (valid range)")
            else:
                print(f"⚠️  ratio = {ratio:.4f} (out of range)")
        
        # Check level
        if level is not None:
            if 0 <= level <= 100:
                print(f"✅ level_percent = {level}% (valid range)")
            else:
                print(f"⚠️  level_percent = {level}% (out of range)")
        
        print(f"✅ ok = {ok}, status = {status}")
        
    except Exception as e:
        print(f"❌ Error calling API: {e}")
    
    print()

def check_recent_logs():
    """Check recent water level logs"""
    print("=" * 60)
    print("3. CHECKING RECENT WATER LEVEL LOGS")
    print("=" * 60)
    
    import subprocess
    result = subprocess.run(
        ["journalctl", "-u", "smartify-dashboard.service", "-n", "50", "--no-pager"],
        capture_output=True,
        text=True
    )
    
    wl_lines = [line for line in result.stdout.split('\n') 
                if 'Water Level Live' in line or 'ADS1115' in line]
    
    if wl_lines:
        print("Recent water level logs:")
        for line in wl_lines[-10:]:  # Show last 10
            print(f"   {line}")
        
        # Check for CONFIG, RAW TUPLE, RESPONSE
        has_config = any('CONFIG:' in line for line in wl_lines)
        has_raw = any('RAW TUPLE' in line for line in wl_lines)
        has_response = any('RESPONSE:' in line for line in wl_lines)
        
        print()
        print("LOG COMPLETENESS:")
        print(f"  CONFIG log:      {'✅' if has_config else '❌'}")
        print(f"  RAW TUPLE log:   {'✅' if has_raw else '❌'}")
        print(f"  RESPONSE log:    {'✅' if has_response else '❌'}")
    else:
        print("⚠️  No recent water level logs found")
    
    print()

def main():
    print("\n" + "=" * 60)
    print("WATER LEVEL DIAGNOSTIC VERIFICATION")
    print("=" * 60)
    print()
    
    check_startup_logs()
    check_live_endpoint()
    check_recent_logs()
    
    print("=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)
    print()

if __name__ == "__main__":
    main()

