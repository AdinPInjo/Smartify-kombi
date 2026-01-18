#!/usr/bin/env python3
"""
CRITICAL FIX: Correct indentation in with db_connect() blocks
Run this immediately to fix IndentationError crash loop
"""

import sys

def fix_indentation():
    """Fix indentation in smartify/app.py"""
    
    with open("smartify/app.py", "r") as f:
        lines = f.readlines()
    
    # Track changes
    fixes = []
    
    # Fix line by line
    for i in range(len(lines)):
        line_num = i + 1
        line = lines[i]
        
        # Check if previous line is 'with db_connect() as conn:'
        if i > 0 and "with db_connect() as conn:" in lines[i-1]:
            # Current line should be indented 4 spaces more than 'with' line
            with_line = lines[i-1]
            with_indent = len(with_line) - len(with_line.lstrip())
            expected_indent = with_indent + 4
            
            # Check current line indentation
            if line.strip():  # Not empty
                current_indent = len(line) - len(line.lstrip())
                if current_indent != expected_indent:
                    # Fix it
                    fixed_line = " " * expected_indent + line.lstrip()
                    lines[i] = fixed_line
                    fixes.append(f"Line {line_num}: Fixed (was {current_indent} spaces, now {expected_indent})")
        
        # Also check lines inside with blocks (lines 853, 857, etc.)
        # These should maintain consistent indentation
        if i >= 2 and "with db_connect() as conn:" in lines[i-2]:
            with_line = lines[i-2]
            with_indent = len(with_line) - len(with_line.lstrip())
            expected_indent = with_indent + 4
            
            if line.strip() and not line.strip().startswith("def "):
                current_indent = len(line) - len(line.lstrip())
                # If line is at wrong indentation and looks like it should be in the with block
                if current_indent < expected_indent and line.strip() and not line.strip().startswith("#"):
                    # Check if it's a continuation of the with block
                    if "cur." in line or "conn." in line or "cutoff" in line or "# Keep" in line:
                        fixed_line = " " * expected_indent + line.lstrip()
                        lines[i] = fixed_line
                        fixes.append(f"Line {line_num}: Fixed continuation (was {current_indent} spaces, now {expected_indent})")
    
    # Write fixed content
    with open("smartify/app.py", "w") as f:
        f.writelines(lines)
    
    # Report
    print("=" * 60)
    print("INDENTATION FIX APPLIED")
    print("=" * 60)
    for fix in fixes:
        print(f"✓ {fix}")
    print(f"\nTotal fixes: {len(fixes)}")
    print("\nNext steps:")
    print("1. ./smartify/.venv/bin/python -m py_compile smartify/app.py")
    print("2. sudo systemctl restart smartify-dashboard")
    print("=" * 60)
    
    return len(fixes)

if __name__ == "__main__":
    try:
        fixes = fix_indentation()
        sys.exit(0 if fixes > 0 else 1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

