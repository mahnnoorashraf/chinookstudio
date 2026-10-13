"""
secure_setup.py  |  Employee sign-in preparation (run once)
-------------------------------------------------------
1. Adds a Password column to the Employee table.
2. Creates a starting password for every employee and stores it as a
   SALTED SHA-256 hash in the form  "<salt>$<hash>".

   * salt  = 16 random bytes (32 hex characters), different for every employee
   * hash  = SHA-256( salt + password ) in hex (64 characters)

   A random salt means two employees with the same password still get
   different hashes, so pre-computed "rainbow table" attacks do not work.
   The plain-text password is never written to the database.

Starting password rule (for testing):  first name in lower case + "@2026"
e.g. Andrew Adams  ->  andrew@2026
"""

import hashlib
import secrets

from rich import box
from rich.console import Console
from rich.table import Table

from database import fetch, fetch_one, transaction

console = Console()


def make_hash(password, salt=None):
    """Return 'salt$sha256(salt+password)'. A new salt is made if none given."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify(password, stored):
    """True if the password matches the stored 'salt$hash' value."""
    salt, _ = stored.split("$", 1)
    return secrets.compare_digest(make_hash(password, salt), stored)


if __name__ == "__main__":
    # 1. Add the column only when it is missing (97 = 32 salt + 1 '$' + 64 hash)
    exists = fetch_one(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        ("Employee", "Password"))
    if not exists:
        with transaction() as cur:
            cur.execute("ALTER TABLE Employee ADD COLUMN Password VARCHAR(97) NULL")
        console.print("[bold green]Password column added to Employee[/]")

    # 2. Hash and store a password for every employee
    _, staff = fetch("SELECT EmployeeId, FirstName, LastName, Title FROM Employee ORDER BY EmployeeId")
    report = Table(title="Employee credentials (salted SHA-256)", box=box.ROUNDED,
                   header_style="bold cyan")
    for col in ("ID", "Employee", "Title", "Login password", "Stored value (salt$hash)"):
        report.add_column(col, overflow="fold")

    with transaction() as cur:
        for emp_id, first, last, title in staff:
            plain = f"{first.lower()}@2026"
            stored = make_hash(plain)
            cur.execute("UPDATE Employee SET Password = %s WHERE EmployeeId = %s",
                        (stored, emp_id))
            report.add_row(str(emp_id), f"{first} {last}", title, plain,
                           f"{stored[:12]}...{stored[-12:]}")
    console.print(report)

    # 3. Self-test: the right password passes, a wrong one fails
    _, rows = fetch("SELECT Password FROM Employee WHERE EmployeeId = %s", (1,))
    console.print(f"Self-test  andrew@2026 -> [green]{verify('andrew@2026', rows[0][0])}[/]   "
                  f"wrong123 -> [red]{verify('wrong123', rows[0][0])}[/]")
