#!/usr/bin/env python3
"""Quick verification that smartify.app imports without NameError"""
import sys

try:
    import smartify.app as app
    print("✓ Import successful - no NameError")
    print(f"✓ Logger defined: {app.logger}")
    print(f"✓ DB_PATH: {app.DB_PATH}")
    print(f"✓ DHT22_PINS: {app.DHT22_PINS}")
    sys.exit(0)
except NameError as e:
    print(f"✗ NameError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

