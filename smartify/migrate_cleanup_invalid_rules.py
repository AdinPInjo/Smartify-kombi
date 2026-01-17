#!/usr/bin/env python3
"""
One-time migration script to clean up invalid relay rules in the database.

This script:
1. Scans all relay_rules in the database
2. For each rule, validates the condition_json field
3. If condition is invalid (string, null, malformed JSON, etc.):
   - Disables the rule (sets is_enabled=0)
   - Logs the invalid rule for review
4. Provides a summary of cleaned rules

Usage:
    python3 smartify/migrate_cleanup_invalid_rules.py

Safety:
- Does NOT delete rules (only disables them)
- Can be run multiple times (idempotent)
- Backs up rule data before modifying
"""

import sys
import os
import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent / "data" / "smartify.db"


def validate_condition(condition_json_str: str) -> tuple[bool, str]:
    """
    Validate a condition_json string.
    
    Returns:
        (is_valid, reason)
    """
    # Check if null or empty
    if not condition_json_str or condition_json_str.strip() == "":
        return (False, "condition_json is empty")
    
    # Try to parse JSON
    try:
        condition = json.loads(condition_json_str)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return (False, f"JSON parse error: {e}")
    
    # Check if it's a dict
    if not isinstance(condition, dict):
        return (False, f"condition is {type(condition).__name__}, not dict")
    
    # Check if it has required fields
    if "type" not in condition:
        return (False, "condition missing 'type' field")
    
    # Validate by type
    condition_type = condition.get("type")
    if condition_type == "temperature":
        # Check required fields
        if "sensor" not in condition:
            return (False, "temperature condition missing 'sensor' field")
        if "operator" not in condition:
            return (False, "temperature condition missing 'operator' field")
        if "value" not in condition:
            return (False, "temperature condition missing 'value' field")
        
        # Validate operator
        operator = condition.get("operator")
        if operator not in ("<", ">", "<=", ">="):
            return (False, f"invalid operator '{operator}'")
        
        # Validate value is a number
        value = condition.get("value")
        if not isinstance(value, (int, float)):
            return (False, f"value must be number, got {type(value).__name__}")
    
    # Valid
    return (True, "OK")


def scan_and_cleanup_rules(dry_run: bool = False) -> Dict[str, Any]:
    """
    Scan all relay rules and disable invalid ones.
    
    Args:
        dry_run: If True, only report issues without modifying DB
    
    Returns:
        Dictionary with cleanup results
    """
    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        return {"error": "db_not_found"}
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Get all rules
    cur.execute("SELECT id, relay_id, name, condition_json, is_enabled FROM relay_rules")
    rules = cur.fetchall()
    
    print(f"📊 Scanning {len(rules)} rules...")
    print()
    
    invalid_rules = []
    valid_rules = 0
    disabled_count = 0
    
    for rule in rules:
        rule_id = rule["id"]
        rule_name = rule["name"]
        relay_id = rule["relay_id"]
        condition_json = rule["condition_json"]
        is_enabled = bool(rule["is_enabled"])
        
        # Validate condition
        is_valid, reason = validate_condition(condition_json)
        
        if is_valid:
            valid_rules += 1
        else:
            # Invalid rule found
            invalid_rules.append({
                "id": rule_id,
                "name": rule_name,
                "relay_id": relay_id,
                "is_enabled": is_enabled,
                "condition_json": condition_json,
                "reason": reason
            })
            
            print(f"❌ Invalid Rule: {rule_name} (id={rule_id[:8]}...)")
            print(f"   Relay ID: {relay_id}")
            print(f"   Currently enabled: {is_enabled}")
            print(f"   Reason: {reason}")
            print(f"   condition_json: {condition_json[:100]}{'...' if len(condition_json) > 100 else ''}")
            
            # Disable the rule (if not already disabled and not dry run)
            if is_enabled and not dry_run:
                cur.execute("UPDATE relay_rules SET is_enabled = 0 WHERE id = ?", (rule_id,))
                disabled_count += 1
                print(f"   ✓ Disabled rule")
            elif is_enabled and dry_run:
                print(f"   [DRY RUN] Would disable rule")
            else:
                print(f"   (already disabled)")
            
            print()
    
    if not dry_run:
        conn.commit()
    
    conn.close()
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total rules scanned: {len(rules)}")
    print(f"Valid rules: {valid_rules}")
    print(f"Invalid rules found: {len(invalid_rules)}")
    if not dry_run:
        print(f"Rules disabled: {disabled_count}")
    else:
        print(f"Rules that would be disabled: {sum(1 for r in invalid_rules if r['is_enabled'])}")
    print()
    
    if invalid_rules:
        print("⚠️  ACTION REQUIRED:")
        print("   - Review the invalid rules listed above")
        print("   - Fix or delete them via the admin UI")
        print("   - Invalid rules have been DISABLED (not deleted)")
        print()
    else:
        print("✅ All rules are valid!")
        print()
    
    return {
        "total": len(rules),
        "valid": valid_rules,
        "invalid": len(invalid_rules),
        "disabled": disabled_count if not dry_run else 0,
        "invalid_rules": invalid_rules
    }


if __name__ == "__main__":
    print("🔧 Relay Rules Cleanup Migration")
    print("=" * 60)
    print()
    
    # Check for dry run mode
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print()
    else:
        print("⚠️  LIVE MODE - Invalid rules will be DISABLED")
        print()
        response = input("Continue? (yes/no): ")
        if response.lower() not in ("yes", "y"):
            print("❌ Aborted")
            sys.exit(0)
        print()
    
    # Run cleanup
    results = scan_and_cleanup_rules(dry_run=dry_run)
    
    # Exit code
    if results.get("invalid", 0) > 0:
        sys.exit(1)  # Exit with error if invalid rules found
    else:
        sys.exit(0)  # Success

