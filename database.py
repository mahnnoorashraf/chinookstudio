"""
database.py  |  Chinook Studio - data access layer
---------------------------------------------------
Every module in the project talks to MySQL through this file.

* Login details are read from a .env file, so no password is written in code.
* transaction() opens a connection, commits if everything works and
  rolls back automatically if any query fails.
* fetch() and fetch_one() run read-only SELECT queries.
All functions expect parameterised SQL (%s placeholders + a params tuple).
"""

import os
from contextlib import contextmanager

import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()  # read the .env file that sits next to this script

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "Chinook"),
}


def connect():
    """Return a new MySQL connection or stop with a readable message."""
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as exc:
        raise SystemExit(f"Cannot reach MySQL -> {exc}")


@contextmanager
def transaction():
    """Usage:  with transaction() as cur: cur.execute(...)
    Commits on success, rolls back on any database error."""
    conn = connect()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Error:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def fetch(sql, params=()):
    """Run a SELECT and return (column_names, rows)."""
    conn = connect()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    columns = [c[0] for c in cur.description]
    cur.close()
    conn.close()
    return columns, rows


def fetch_one(sql, params=()):
    """Run a SELECT that returns a single value."""
    _, rows = fetch(sql, params)
    return rows[0][0] if rows else None


# --------------------------------------------------------------------------
# Health check: run "python database.py" to confirm the connection works
# --------------------------------------------------------------------------
if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()
    tables = ["Artist", "Album", "Track", "Genre", "MediaType", "Playlist",
              "PlaylistTrack", "Customer", "Employee", "Invoice", "InvoiceLine"]

    report = Table(title="Database Health Check", header_style="bold magenta")
    report.add_column("Table", style="cyan")
    report.add_column("Rows", justify="right", style="green")
    for name in tables:                       # names come from a fixed list
        report.add_row(name, f"{fetch_one(f'SELECT COUNT(*) FROM {name}'):,}")

    console.print(f"[bold green]Connected[/] to [bold]{DB_CONFIG['database']}[/] "
                  f"on {DB_CONFIG['host']}:{DB_CONFIG['port']} as {DB_CONFIG['user']}")
    console.print(report)