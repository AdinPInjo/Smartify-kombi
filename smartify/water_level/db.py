"""Water level database operations."""

import sqlite3
import time
from typing import Optional, Dict, Any
from pathlib import Path

from .models import WaterLevelSettings, WaterLevelSnapshot


# DB_PATH will be injected from app
_DB_PATH: Optional[Path] = None


def set_db_path(db_path: Path) -> None:
    """Set the database path (called from app initialization)."""
    global _DB_PATH
    _DB_PATH = db_path


def _get_db_path() -> Path:
    """Get the database path."""
    if _DB_PATH is None:
        raise RuntimeError("DB path not set. Call set_db_path() first.")
    return _DB_PATH


def db_init_water_level(conn: sqlite3.Connection) -> None:
    """
    Initialize water level database tables and run migrations.
    
    Must be called during app startup after DB connection is established.
    """
    cur = conn.cursor()
    
    # Water level snapshot table (single-row upsert pattern)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS water_level_snapshot (
            id INTEGER PRIMARY KEY CHECK(id=1),
            avg_voltage REAL NOT NULL,
            level_percent INTEGER NOT NULL,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            avg_signal_voltage REAL,
            avg_supply_div_voltage REAL,
            supply_voltage_est REAL,
            ratio REAL
        );
        """
    )
    
    # Migrate water_level_snapshot table if it exists with old schema
    cur.execute("PRAGMA table_info(water_level_snapshot)")
    snapshot_columns = [row[1] for row in cur.fetchall()]
    
    if snapshot_columns:  # Table exists
        # Check if new columns are missing
        missing_columns = {
            "avg_signal_voltage": "REAL",
            "avg_supply_div_voltage": "REAL",
            "supply_voltage_est": "REAL",
            "ratio": "REAL"
        }
        
        for col_name, col_type in missing_columns.items():
            if col_name not in snapshot_columns:
                try:
                    cur.execute(f"ALTER TABLE water_level_snapshot ADD COLUMN {col_name} {col_type}")
                    print(f"[DB] Migrated water_level_snapshot: added column {col_name}")
                except sqlite3.OperationalError as e:
                    print(f"[DB] Warning: Could not add column {col_name}: {e}")
        
        # Check if id column has CHECK constraint (new schema)
        # If not, this is old schema with AUTOINCREMENT - need to handle id=1 constraint
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='water_level_snapshot'")
        table_sql = cur.fetchone()
        if table_sql and "CHECK(id=1)" not in table_sql[0]:
            # Old schema: id is AUTOINCREMENT, not single-row
            # We'll keep using it as-is; upsert will handle id=1 via INSERT ... ON CONFLICT
            print("[DB] Water level snapshot using legacy AUTOINCREMENT schema (backward compatible)")
    
    # Enable WAL mode for better concurrency (run once at init)
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError as e:
        print(f"[DB] Warning: Could not set PRAGMA: {e}")
    
    # Water level settings table (calibration)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS water_level_settings (
            id TEXT PRIMARY KEY DEFAULT 'default',
            full_voltage REAL NOT NULL,
            empty_voltage REAL NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """
    )
    
    # Check if new columns exist, add them if missing (migration)
    cur.execute("PRAGMA table_info(water_level_settings)")
    existing_columns = [row[1] for row in cur.fetchall()]
    
    new_columns = {
        "use_supply_normalization": "BOOLEAN DEFAULT 1",
        "adc_channel_signal": "INTEGER DEFAULT 0",
        "adc_channel_supply": "INTEGER DEFAULT 1",
        "divider_r_top": "REAL DEFAULT 47000",
        "divider_r_bottom": "REAL DEFAULT 10000",
        "full_ratio": "REAL",
        "empty_ratio": "REAL",
        "full_supply_voltage": "REAL",
        "empty_supply_voltage": "REAL"
    }
    
    for col_name, col_def in new_columns.items():
        if col_name not in existing_columns:
            try:
                cur.execute(f"ALTER TABLE water_level_settings ADD COLUMN {col_name} {col_def}")
                print(f"[DB] Added column water_level_settings.{col_name}")
            except sqlite3.OperationalError as e:
                print(f"[DB] Warning: Could not add column {col_name}: {e}")
    
    # Initialize default calibration if not exists
    cur.execute("SELECT COUNT(*) FROM water_level_settings WHERE id = 'default'")
    if cur.fetchone()[0] == 0:
        now = int(time.time())
        cur.execute(
            """INSERT INTO water_level_settings 
               (id, full_voltage, empty_voltage, updated_at, use_supply_normalization, 
                adc_channel_signal, adc_channel_supply, divider_r_top, divider_r_bottom)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("default", 0.497, 2.230, now, 1, 0, 1, 47000.0, 10000.0)
        )
        print(f"[DB] Initialized water_level_settings with defaults: full=0.497V, empty=2.230V, normalization enabled")


def _set_connection_pragmas(conn: sqlite3.Connection) -> None:
    """Set recommended PRAGMA settings for a connection."""
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    # Verify settings were applied
    cur.execute("PRAGMA busy_timeout")
    timeout = cur.fetchone()[0]
    if timeout != 5000:
        print(f"[DB] Warning: busy_timeout is {timeout}, expected 5000")


def db_get_water_level_settings(conn: sqlite3.Connection) -> WaterLevelSettings:
    """
    Get water level calibration settings from database.
    
    Auto-cleans invalid ratio values (> 1.0) if normalization is enabled.
    """
    FALLBACK_FULL_V = 0.497
    FALLBACK_EMPTY_V = 2.230
    
    try:
        _set_connection_pragmas(conn)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM water_level_settings WHERE id = 'default'")
        row = cur.fetchone()
        
        if row:
            settings: Dict[str, Any] = dict(row)
            # Auto-clear invalid ratio values if normalization is enabled
            use_normalization = settings.get("use_supply_normalization", True)
            if use_normalization:
                full_ratio = settings.get("full_ratio")
                empty_ratio = settings.get("empty_ratio")
                
                # If ratios look like voltages (> 1.0), clear them
                cleared = False
                if full_ratio is not None and full_ratio > 1.0:
                    print(f"[Water Level] Auto-clearing invalid full_ratio={full_ratio} (looks like voltage, ratios must be < 1.0)")
                    settings["full_ratio"] = None
                    cleared = True
                if empty_ratio is not None and empty_ratio > 1.0:
                    print(f"[Water Level] Auto-clearing invalid empty_ratio={empty_ratio} (looks like voltage, ratios must be < 1.0)")
                    settings["empty_ratio"] = None
                    cleared = True
                
                # Update DB if we cleared invalid ratios
                if cleared:
                    cur.execute(
                        """UPDATE water_level_settings 
                           SET full_ratio = ?, empty_ratio = ?
                           WHERE id = 'default'""",
                        (settings.get("full_ratio"), settings.get("empty_ratio"))
                    )
                    conn.commit()
                    print("[Water Level] Updated DB: cleared invalid ratio values")
            
            return settings  # type: ignore
        else:
            # Return defaults if not found
            now = int(time.time())
            return {
                "id": "default",
                "full_voltage": FALLBACK_FULL_V,
                "empty_voltage": FALLBACK_EMPTY_V,
                "updated_at": now
            }  # type: ignore
    except Exception as e:
        print(f"[Water Level] Error loading settings from DB: {e}")
        # Return safe fallback on any error
        now = int(time.time())
        return {
            "id": "default",
            "full_voltage": FALLBACK_FULL_V,
            "empty_voltage": FALLBACK_EMPTY_V,
            "use_supply_normalization": True,
            "adc_channel_signal": 0,
            "adc_channel_supply": 1,
            "divider_r_top": 47000.0,
            "divider_r_bottom": 10000.0,
            "updated_at": now
        }  # type: ignore


def db_update_water_level_settings(
    conn: sqlite3.Connection,
    full_voltage: Optional[float] = None,
    empty_voltage: Optional[float] = None,
    use_supply_normalization: Optional[bool] = None,
    adc_channel_signal: Optional[int] = None,
    adc_channel_supply: Optional[int] = None,
    divider_r_top: Optional[float] = None,
    divider_r_bottom: Optional[float] = None,
    full_ratio: Optional[float] = None,
    empty_ratio: Optional[float] = None,
    full_supply_voltage: Optional[float] = None,
    empty_supply_voltage: Optional[float] = None
) -> WaterLevelSettings:
    """Update water level calibration settings in database."""
    _set_connection_pragmas(conn)
    conn.row_factory = sqlite3.Row
    
    # Get current settings to preserve values not being updated
    cur = conn.cursor()
    cur.execute("SELECT * FROM water_level_settings WHERE id = 'default'")
    row = cur.fetchone()
    if row:
        current = dict(row)
    else:
        current = {}
    
    # Use provided values or keep current values
    now = int(time.time())
    final_full_voltage = float(full_voltage) if full_voltage is not None else float(current.get("full_voltage", 0.497))
    final_empty_voltage = float(empty_voltage) if empty_voltage is not None else float(current.get("empty_voltage", 2.230))
    final_use_normalization = 1 if bool(use_supply_normalization) else 0 if use_supply_normalization is not None else (1 if bool(current.get("use_supply_normalization", True)) else 0)
    final_channel_signal = int(adc_channel_signal) if adc_channel_signal is not None else int(current.get("adc_channel_signal", 0))
    final_channel_supply = int(adc_channel_supply) if adc_channel_supply is not None else int(current.get("adc_channel_supply", 1))
    final_r_top = float(divider_r_top) if divider_r_top is not None else float(current.get("divider_r_top", 47000.0))
    final_r_bottom = float(divider_r_bottom) if divider_r_bottom is not None else float(current.get("divider_r_bottom", 10000.0))
    final_full_ratio = float(full_ratio) if full_ratio is not None else (float(current.get("full_ratio")) if current.get("full_ratio") is not None else None)
    final_empty_ratio = float(empty_ratio) if empty_ratio is not None else (float(current.get("empty_ratio")) if current.get("empty_ratio") is not None else None)
    final_full_supply = float(full_supply_voltage) if full_supply_voltage is not None else (float(current.get("full_supply_voltage")) if current.get("full_supply_voltage") is not None else None)
    final_empty_supply = float(empty_supply_voltage) if empty_supply_voltage is not None else (float(current.get("empty_supply_voltage")) if current.get("empty_supply_voltage") is not None else None)
    
    # Check which columns exist
    cur.execute("PRAGMA table_info(water_level_settings)")
    existing_columns = [row[1] for row in cur.fetchall()]
    has_new_columns = "use_supply_normalization" in existing_columns
    
    if has_new_columns:
        cur.execute(
            """UPDATE water_level_settings SET
               full_voltage = ?,
               empty_voltage = ?,
               use_supply_normalization = ?,
               adc_channel_signal = ?,
               adc_channel_supply = ?,
               divider_r_top = ?,
               divider_r_bottom = ?,
               full_ratio = ?,
               empty_ratio = ?,
               full_supply_voltage = ?,
               empty_supply_voltage = ?,
               updated_at = ?
               WHERE id = 'default'""",
            (final_full_voltage, final_empty_voltage, final_use_normalization,
             final_channel_signal, final_channel_supply, final_r_top, final_r_bottom,
             final_full_ratio, final_empty_ratio, final_full_supply, final_empty_supply, now)
        )
    else:
        # Old schema - only update basic fields
        cur.execute(
            """UPDATE water_level_settings SET
               full_voltage = ?,
               empty_voltage = ?,
               updated_at = ?
               WHERE id = 'default'""",
            (final_full_voltage, final_empty_voltage, now)
        )
    
    conn.commit()
    return db_get_water_level_settings(conn)


def db_get_water_level_snapshot(conn: sqlite3.Connection) -> Optional[WaterLevelSnapshot]:
    """Get the latest water level snapshot from database."""
    _set_connection_pragmas(conn)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Try id=1 first (new schema), fall back to latest row (old schema)
    cur.execute("SELECT * FROM water_level_snapshot WHERE id = 1")
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT * FROM water_level_snapshot ORDER BY updated_at DESC LIMIT 1")
        row = cur.fetchone()
    return dict(row) if row else None  # type: ignore


def db_upsert_water_snapshot(
    conn: sqlite3.Connection,
    snapshot: Dict[str, Any]
) -> None:
    """
    Insert or update water level snapshot in database.
    
    Supports both old (AUTOINCREMENT) and new (id=1 CHECK) schemas.
    Uses upsert pattern to eliminate DELETE+INSERT database locks.
    """
    _set_connection_pragmas(conn)
    cur = conn.cursor()
    
    now = int(time.time())
    created_at = snapshot.get("created_at", now)
    
    # Check which columns exist in the table
    cur.execute("PRAGMA table_info(water_level_snapshot)")
    existing_cols = {row[1] for row in cur.fetchall()}
    
    # Build column list and values based on what exists in schema
    base_cols = ["avg_voltage", "level_percent", "status", "message", "updated_at", "created_at"]
    optional_cols = ["avg_signal_voltage", "avg_supply_div_voltage", "supply_voltage_est", "ratio"]
    
    cols_to_write = base_cols + [c for c in optional_cols if c in existing_cols]
    values_to_write = [
        snapshot.get("avg_voltage", 0.0),
        snapshot.get("level_percent", 0),
        snapshot.get("status", "unknown"),
        snapshot.get("message", ""),
        snapshot.get("updated_at", now),
        created_at
    ]
    for col in optional_cols:
        if col in existing_cols:
            values_to_write.append(snapshot.get(col))
    
    # Try upsert with id=1 first (new schema)
    try:
        placeholders = ", ".join(["?"] * len(values_to_write))
        update_clause = ", ".join([f"{col} = excluded.{col}" for col in cols_to_write])
        
        cur.execute(
            f"""INSERT INTO water_level_snapshot 
               (id, {", ".join(cols_to_write)})
               VALUES (1, {placeholders})
               ON CONFLICT(id) DO UPDATE SET {update_clause}
            """,
            values_to_write
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Old schema: AUTOINCREMENT without CHECK constraint
        # Delete old rows and insert new one
        cur.execute("DELETE FROM water_level_snapshot WHERE id != 1 OR id IS NULL")
        placeholders = ", ".join(["?"] * len(values_to_write))
        cur.execute(
            f"""INSERT OR REPLACE INTO water_level_snapshot 
               (id, {", ".join(cols_to_write)})
               VALUES (1, {placeholders})
            """,
            values_to_write
        )
        conn.commit()


# Backward compatibility alias
db_insert_water_snapshot = db_upsert_water_snapshot

