#!/usr/bin/env python3
"""Fix indentation in 'with db_connect() as conn:' blocks"""

# Read file
with open("smartify/app.py", "r") as f:
    lines = f.readlines()

# Track if we're inside a 'with db_connect()' block that needs fixing
in_with_block = False
with_indent = 0

fixed_lines = []
fixes_applied = 0

for i, line in enumerate(lines):
    line_num = i + 1
    
    # Detect 'with db_connect() as conn:' lines
    if "with db_connect() as conn:" in line:
        in_with_block = True
        with_indent = len(line) - len(line.lstrip())
        fixed_lines.append(line)
        continue
    
    # If we're in a with block, check if the next line needs indenting
    if in_with_block:
        current_indent = len(line) - len(line.lstrip())
        
        # If line is not indented more than 'with' statement, exit block
        if line.strip() and current_indent <= with_indent:
            in_with_block = False
            fixed_lines.append(line)
            continue
        
        # If line should be indented under 'with' but isn't (e.g., 'cur = conn.cursor()')
        # It should be at with_indent + 4
        expected_indent = with_indent + 4
        
        if line.strip() and current_indent != expected_indent and current_indent == with_indent:
            # This line needs fixing - add 4 spaces
            fixed_line = " " * expected_indent + line.lstrip()
            fixed_lines.append(fixed_line)
            fixes_applied += 1
            print(f"Line {line_num}: Fixed indentation (was {current_indent}, now {expected_indent})")
            print(f"  Before: {repr(line.rstrip())}")
            print(f"  After:  {repr(fixed_line.rstrip())}")
            continue
    
    # Default: keep line as-is
    fixed_lines.append(line)

# Write fixed content
with open("smartify/app.py", "w") as f:
    f.writelines(fixed_lines)

print(f"\n✅ Applied {fixes_applied} indentation fixes")

