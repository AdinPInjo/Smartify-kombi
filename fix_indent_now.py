#!/usr/bin/env python3
"""Fix indentation at line 3684 in smartify/app.py"""
from pathlib import Path

app_py = Path(__file__).parent / "smartify" / "app.py"
lines = app_py.read_text().splitlines()

print(f"Before fix, line 3684: {repr(lines[3683])}")

# Fix lines 3684-3688 (indices 3683-3687)
lines[3683] = '                return JSONResponse({'
lines[3684] = '                    "ok": False,'
lines[3685] = '                    "error": "invalid_action",'
lines[3686] = '                    "message": action_error or "Invalid action payload"'
lines[3687] = '                }, status_code=400)'

print(f"After fix, line 3684: {repr(lines[3683])}")

app_py.write_text('\n'.join(lines) + '\n')
print("✓ Fixed indentation successfully")

