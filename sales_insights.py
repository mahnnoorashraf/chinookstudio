"""
sales_insights.py  |  Data Analysis with pandas
---------------------------------------------------------------
Pipeline:
  1. Extract  - load Invoice, InvoiceLine, Track and Genre into DataFrames
  2. Combine  - join them on InvoiceId, TrackId and GenreId
  3. Measure  - LineTotal = UnitPrice x Quantity, then revenue per genre
                and per billing country (with share of total revenue)
  4. Publish  - top 5 genres and top 5 countries saved to separate CSV
                files, plus a chart image of both rankings

Revenue uses InvoiceLine.UnitPrice: the price the customer actually paid.
Track.UnitPrice is the current catalogue price (catalog_ops.py changes Jazz prices).
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")                     # draw charts without opening a window
import matplotlib.pyplot as plt
import pandas as pd
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from database import fetch

console = Console()
EXPORT_DIR = Path(__file__).with_name("exports")
EXPORT_DIR.mkdir(exist_ok=True)

# Only these tables/columns are ever loaded (fixed list, no user input)
SOURCES = {
    "Invoice":     ["InvoiceId", "CustomerId", "InvoiceDate", "BillingCountry", "Total"],
    "InvoiceLine": ["InvoiceLineId", "InvoiceId", "TrackId", "UnitPrice", "Quantity"],
    "Track":       ["TrackId", "Name", "GenreId"],
    "Genre":       ["GenreId", "Name"],
}


def load_frame(table):
    """Read one table into a DataFrame."""
    columns, rows = fetch(f"SELECT {', '.join(SOURCES[table])} FROM {table}")
    return pd.DataFrame(rows, columns=columns)


def render(df, title, colour="cyan", money=()):
    """Print a DataFrame as a rich table; money columns get a $ format."""
    grid = Table(title=title, box=box.SIMPLE_HEAVY, header_style=f"bold {colour}")
    for col in df.columns:
        grid.add_column(str(col), justify="right" if col in money else "left")
    for _, row in df.iterrows():
        grid.add_row(*[f"${v:,.2f}" if c in money else str(v) for c, v in row.items()])
    console.print(grid)


# ---------------------------------------------------------------- 1. extract
console.rule("[bold cyan]Stage 1 - Extract")
frames = {name: load_frame(name) for name in SOURCES}
summary = Table(box=box.ROUNDED, header_style="bold cyan")
summary.add_column("DataFrame"); summary.add_column("Rows", justify="right"); summary.add_column("Columns")
for name, df in frames.items():
    summary.add_row(name, f"{len(df):,}", ", ".join(df.columns))
console.print(summary)

invoices, lines, tracks, genres = (frames[n] for n in SOURCES)
lines["UnitPrice"] = lines["UnitPrice"].astype(float)      # DECIMAL -> float
invoices["Total"] = invoices["Total"].astype(float)

# ---------------------------------------------------------------- 2. combine
console.rule("[bold magenta]Stage 2 - Combine")
sales = (
    lines
    .merge(tracks.rename(columns={"Name": "TrackName"}), on="TrackId",
           how="left", validate="many_to_one")
    .merge(genres.rename(columns={"Name": "Genre"}), on="GenreId",
           how="left", validate="many_to_one")
    .merge(invoices[["InvoiceId", "InvoiceDate", "BillingCountry"]], on="InvoiceId",
           how="left", validate="many_to_one")
)
# validate="many_to_one" makes pandas stop if a key were duplicated,
# so every invoice line is matched to exactly one track, genre and invoice.
render(sales[["InvoiceLineId", "InvoiceId", "TrackName", "Genre", "BillingCountry"]].head(8),
       f"Sample of the combined sales data ({len(sales):,} rows)", "magenta")

# ---------------------------------------------------------------- 3. measure
console.rule("[bold green]Stage 3 - Measure")
sales["LineTotal"] = (sales["UnitPrice"] * sales["Quantity"]).round(2)
grand_total = sales["LineTotal"].sum()


def revenue_by(column):
    """Revenue, number of lines and % share for each value of a column."""
    out = (sales.groupby(column)
                .agg(Revenue=("LineTotal", "sum"), Lines=("InvoiceLineId", "count"))
                .sort_values("Revenue", ascending=False)
                .reset_index())
    out["Share %"] = (out["Revenue"] / grand_total * 100).round(1)
    out["Revenue"] = out["Revenue"].round(2)
    return out


genre_revenue = revenue_by("Genre")
country_revenue = revenue_by("BillingCountry").rename(columns={"BillingCountry": "Country"})

render(sales[["InvoiceLineId", "TrackName", "UnitPrice", "Quantity", "LineTotal"]].head(5),
       "LineTotal = UnitPrice x Quantity", "green", money=("UnitPrice", "LineTotal"))
render(genre_revenue, "Revenue by genre", "green", money=("Revenue",))
render(country_revenue, "Revenue by billing country", "green", money=("Revenue",))

matches = round(grand_total, 2) == round(invoices["Total"].sum(), 2)
console.print(Panel(
    f"Sum of LineTotal     : ${grand_total:,.2f}\n"
    f"Sum of Invoice.Total : ${invoices['Total'].sum():,.2f}\n"
    f"Reconciled           : {'YES' if matches else 'NO'}",
    title="Revenue reconciliation", border_style="green" if matches else "red"))

# ---------------------------------------------------------------- 4. publish
console.rule("[bold yellow]Stage 4 - Publish")
top_genres = genre_revenue.nlargest(5, "Revenue").reset_index(drop=True)
top_countries = country_revenue.nlargest(5, "Revenue").reset_index(drop=True)
top_genres.insert(0, "Rank", range(1, 6))
top_countries.insert(0, "Rank", range(1, 6))

genre_csv = EXPORT_DIR / "top5_genres_by_revenue.csv"
country_csv = EXPORT_DIR / "top5_countries_by_revenue.csv"
top_genres.to_csv(genre_csv, index=False)
top_countries.to_csv(country_csv, index=False)

render(top_genres, "Top 5 genres", "yellow", money=("Revenue",))
render(top_countries, "Top 5 countries", "yellow", money=("Revenue",))

# Chart: two horizontal bar charts side by side
fig, (left, right) = plt.subplots(1, 2, figsize=(12, 4.5))
for axis, data, label, heading, colour in [
        (left, top_genres, "Genre", "Top 5 genres by revenue", "#7c3aed"),
        (right, top_countries, "Country", "Top 5 countries by revenue", "#0ea5e9")]:
    axis.barh(data[label][::-1], data["Revenue"][::-1], color=colour)
    axis.set_title(heading, fontweight="bold")
    axis.set_xlabel("Revenue ($)")
    for y, value in enumerate(data["Revenue"][::-1]):
        axis.text(value, y, f" ${value:,.2f}", va="center", fontsize=9)
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_xlim(0, data["Revenue"].max() * 1.25)
fig.tight_layout()
chart_png = EXPORT_DIR / "top5_revenue_chart.png"
fig.savefig(chart_png, dpi=150)

console.print(Panel(f"{genre_csv.name}\n{country_csv.name}\n{chart_png.name}",
                    title=f"Saved to {EXPORT_DIR.name}/", border_style="yellow"))
