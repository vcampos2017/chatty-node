import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "chatty_node.db")


def log_sensor(node, soil, temp, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO sensor_readings (node_name, soil_moisture, temperature, status)
    VALUES (?, ?, ?, ?)
    """, (node, soil, temp, status))

    conn.commit()
    conn.close()


def log_action(node, action, result, notes=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO actions (node_name, action_type, result, notes)
    VALUES (?, ?, ?, ?)
    """, (node, action, result, notes))

    conn.commit()
    conn.close()