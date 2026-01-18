#!/usr/bin/env python3
"""Fix indentation errors in smartify/app.py"""
from pathlib import Path

app_py = Path(__file__).parent / "smartify" / "app.py"
lines = app_py.read_text().splitlines()

print("Fixing indentation errors...")

# Fix 1: Lines 2780, 2783 (sensor unavailable block) - should be 16 spaces
if '                                pending = True' in lines[2779]:
    lines[2779] = '                pending = True'
    print("✓ Fixed line 2780: pending = True (sensor block)")

if '                                source = "sensor"' in lines[2782]:
    lines[2782] = '                source = "sensor"'
    print("✓ Fixed line 2783: source = \"sensor\"")

# Fix 2: Line 2789 (min_on block) - should be 24 spaces
if '                                pending = True' in lines[2788]:
    lines[2788] = '                        pending = True'
    print("✓ Fixed line 2789: pending = True (min_on block)")

# Fix 3: Lines 3684-3688 (action validation) - return block needs proper indentation
if 'if not is_valid_action or action is None:' in lines[3682]:
    if '            return JSONResponse({' in lines[3683]:
        lines[3683] = '                return JSONResponse({'
        lines[3684] = '                    "ok": False,'
        lines[3685] = '                    "error": "invalid_action",'
        lines[3686] = '                    "message": action_error or "Invalid action payload"'
        lines[3687] = '                }, status_code=400)'
        print("✓ Fixed lines 3684-3688: action validation return block")

# Write the fixed file
app_py.write_text('\n'.join(lines) + '\n')
print("\n✓ All indentation fixes applied successfully")
print("\nRun: python3 -m py_compile smartify/app.py")

