import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "chatty_node.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sensor_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        node_name TEXT,
        soil_moisture REAL,
        temperature REAL,
        status TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        node_name TEXT,
        action_type TEXT,
        result TEXT,
        notes TEXT
    )
    """)

    conn.commit()
    conn.close()


def log_sensor(node, soil, temp, status):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO sensor_readings (node_name, soil_moisture, temperature, status)
    VALUES (?, ?, ?, ?)
    """, (node, soil, temp, status))

    conn.commit()
    conn.close()


def log_action(node, action, result, notes=""):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO actions (node_name, action_type, result, notes)
    VALUES (?, ?, ?, ?)
    """, (node, action, result, notes))

    conn.commit()
    conn.close()


def get_last_status(offset=1):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT status
    FROM sensor_readings
    ORDER BY id DESC
    LIMIT 1 OFFSET ?
    """, (offset,))

    row = cur.fetchone()
    conn.close()

    return row[0] if row else None
