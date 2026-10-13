# Chinook Studio

Chinook Studio is a Python desktop app and set of command-line tools for exploring and managing the [Chinook music-store database](https://github.com/lerocha/chinook-database). The desktop app uses Tkinter with ttkbootstrap, and the reporting script uses pandas and Matplotlib.

## Features

- **Employee sign-in:** Verifies employee passwords stored in the database.
- **Dashboard:** Summarizes store activity and recent invoices.
- **Track catalogue:** Search, add, update, and delete tracks.
- **Customer reports:** View a customer's invoices and export them to CSV.
- **Sales insights:** Calculate revenue by genre and country, reconcile invoice totals, and create CSV reports and a chart.
- **Catalogue operations:** Preview tracks, register a genre, update Jazz prices, and demonstrate playlist creation and deletion.

## Requirements

- Python 3.10 or newer
- MySQL Server with the Chinook database imported

## Setup

Open PowerShell in the project folder and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with the connection details for your local MySQL server. For example:

```dotenv
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your-local-password
DB_NAME=Chinook
```

Make sure the Chinook schema and sample data are loaded into that MySQL server before running the scripts. The application expects the standard Chinook tables, including `Employee`, `Track`, `Invoice`, and `InvoiceLine`.

## Run

Run the sales analysis and create its reports:

```powershell
py sales_insights.py
```

Run the catalogue operations:

```powershell
py catalog_ops.py
```

Prepare employee sign-in, then launch the desktop app:

```powershell
py secure_setup.py
py studio_app.py
```

`secure_setup.py` adds the `Employee.Password` column if needed and assigns initial passwords based on each employee's first name, followed by `@2026`. It prints those credentials when it runs and replaces the stored passwords each time it is run. This is a demo setup for a local sample database only: do not use these credentials or the SHA-256 password scheme for a production system.

Catalogue operations change database contents (including Jazz track prices) and create then remove a playlist. Use a local/test database when running them.

## Generated files and configuration

The sales report writes its CSV files and chart to `exports/`. The customer-report screen can also export invoice data to a CSV file you choose. Generated exports, `.env`, Python virtual environments, and cache files are excluded from Git; keep local database credentials and customer data private.

## Project files

- `database.py` — MySQL connection, transaction, and query helpers
- `catalog_ops.py` — Catalogue and playlist operations
- `sales_insights.py` — Sales analysis and report generation
- `secure_setup.py` — Demo employee sign-in setup
- `studio_app.py` — Tkinter desktop application
- `.env.example` — Local database configuration template
- `requirements.txt` — Python package dependencies
