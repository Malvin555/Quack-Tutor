"""HTTP-ish handlers backed by a tiny SQL database."""
import sqlite3

from auth import login

DB_PATH = "app.db"


def run_query(sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def get_user_handler(user_id: int) -> dict:
    """Route handler: fetch a user row from the database."""
    rows = run_query("SELECT id, name FROM users WHERE id = ?", (user_id,))
    return {"user": rows[0] if rows else None}


def login_endpoint(user_id: int, stored: str, supplied: str) -> dict:
    token = login(user_id, stored, supplied)
    return {"ok": token is not None, "token": token}
