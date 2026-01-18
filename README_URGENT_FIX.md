# 🚨 URGENT: IndentationError Fix Required

## Problem
`smartify/app.py` has indentation errors causing crash loop:
```
IndentationError: expected an indented block after 'with' statement on line 836
```

## Fix (Run on Raspberry Pi)

```bash
cd /home/adinpinjo/repos/Smartify-kombi

# Pull latest changes
git pull

# Run fix script
python3 FIX_INDENTATION_NOW.py

# Verify compilation
./smartify/.venv/bin/python -m py_compile smartify/app.py

# Restart service
sudo systemctl restart smartify-dashboard

# Check status
sudo systemctl status smartify-dashboard
curl -sS http://127.0.0.1:8000/api/sensors/latest
```

## What the Fix Does

Corrects indentation in 4 `with db_connect() as conn:` blocks:
- Line 836: `db_insert_temp()`
- Line 847: `db_insert_sensor_sample()`
- Line 872: `db_update_sensor_snapshot()`
- Line 952: `db_get_sensor_snapshot()`

Lines inside these `with` blocks were not indented properly, causing Python syntax errors.

## Expected Result

After running the fix:
- ✅ `py_compile` passes without errors
- ✅ Service starts and stays running
- ✅ API responds at `http://127.0.0.1:8000`
- ✅ No more "Cannot operate on a closed database" errors

## If Fix Fails

Check the script output for details, then manually inspect lines 836-858, 872-924, and 952-956 in `smartify/app.py`.

Each line after `with db_connect() as conn:` must be indented 4 spaces deeper than the `with` line.

