import sqlite3

DB_PATH = "log.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            distance_km REAL NOT NULL,
            duration_min REAL NOT NULL,
            notes TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def insert_entry(date: str, distance_km: float, duration_min: float, notes: str) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO entries (date, distance_km, duration_min, notes) VALUES (?, ?, ?, ?)",
        (date, distance_km, duration_min, notes),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def get_all_entries():
    conn = get_connection()
    cursor = conn.execute(
        "SELECT id, date, distance_km, duration_min, notes FROM entries ORDER BY date DESC, id DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    return rows
