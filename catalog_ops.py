"""
catalog_ops.py  |  Database Setup and Manipulation
-----------------------------------------------------------------
Operations performed on the Chinook catalogue:
  1. Preview the first 20 tracks (TrackId, Name, Composer, UnitPrice)
  2. Register a new genre called "Lo-fi"
  3. Apply a 10% price increase to every Jazz track (before/after view)
  4. Build a "Test Playlist" from the 3 best-selling tracks, then remove it
     (child rows in PlaylistTrack first, then the Playlist row)

Every statement is parameterised and every change runs inside
database.transaction(), which commits or rolls back automatically.
"""

from mysql.connector import IntegrityError
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from database import fetch, fetch_one, transaction

console = Console()


def show(title, columns, rows, colour="cyan"):
    """Render query results as a styled rich table."""
    grid = Table(title=title, box=box.ROUNDED, header_style=f"bold {colour}",
                 title_style="bold white", show_lines=False)
    for col in columns:
        grid.add_column(str(col), overflow="ellipsis", max_width=42)
    for row in rows:
        grid.add_row(*["-" if v is None else str(v) for v in row])
    console.print(grid)


# ---------------------------------------------------------------- operation 1
def preview_tracks(limit=20):
    console.rule("[bold cyan]Operation 1 - Track preview")
    cols, rows = fetch(
        "SELECT TrackId, Name, Composer, UnitPrice FROM Track "
        "ORDER BY TrackId LIMIT %s", (limit,))
    show(f"First {limit} tracks in the catalogue", cols, rows)


# ---------------------------------------------------------------- operation 2
def register_genre(name="Lo-fi"):
    console.rule("[bold green]Operation 2 - New genre")
    existing = fetch_one("SELECT GenreId FROM Genre WHERE Name = %s", (name,))
    if existing:
        console.print(Panel(f'"{name}" is already registered (GenreId {existing}).',
                            border_style="yellow"))
    else:
        with transaction() as cur:
            # GenreId has no AUTO_INCREMENT, so the next id is calculated
            cur.execute("SELECT COALESCE(MAX(GenreId), 0) + 1 FROM Genre")
            new_id = cur.fetchone()[0]
            cur.execute("INSERT INTO Genre (GenreId, Name) VALUES (%s, %s)", (new_id, name))
        console.print(Panel(f'Genre [bold]"{name}"[/] saved with GenreId [bold]{new_id}[/]',
                            title="INSERT successful", border_style="green"))
    cols, rows = fetch("SELECT GenreId, Name FROM Genre ORDER BY GenreId")
    show("Genre table after the insert", cols, rows, "green")


# ---------------------------------------------------------------- operation 3
def reprice_genre(genre="Jazz", rate=0.10):
    console.rule(f"[bold magenta]Operation 3 - {genre} price increase")
    lookup = ("SELECT t.TrackId, t.Name, t.UnitPrice FROM Track t "
              "JOIN Genre g ON g.GenreId = t.GenreId WHERE g.Name = %s ORDER BY t.TrackId")
    _, before = fetch(lookup, (genre,))
    old_price = {tid: price for tid, _, price in before}

    with transaction() as cur:
        cur.execute(
            "UPDATE Track t JOIN Genre g ON g.GenreId = t.GenreId "
            "SET t.UnitPrice = ROUND(t.UnitPrice * %s, 2) WHERE g.Name = %s",
            (1 + rate, genre))
        changed = cur.rowcount

    _, after = fetch(lookup, (genre,))
    rows = [(tid, name, old_price[tid], new, f"+{new - old_price[tid]:.2f}")
            for tid, name, new in after]
    console.print(Panel(f"{changed} {genre} tracks repriced by {rate:.0%}",
                        border_style="magenta"))
    show(f"{genre} tracks - before and after", ["TrackId", "Name", "Before", "After", "Change"],
         rows, "magenta")


# ---------------------------------------------------------------- operation 4
def playlist_lifecycle(name="Test Playlist"):
    console.rule("[bold yellow]Operation 4 - Playlist create and remove")

    # Pick the 3 best-selling tracks as the playlist content
    _, top = fetch(
        "SELECT TrackId FROM InvoiceLine GROUP BY TrackId "
        "ORDER BY SUM(Quantity) DESC, TrackId LIMIT %s", (3,))
    track_ids = [r[0] for r in top]

    with transaction() as cur:
        cur.execute("SELECT COALESCE(MAX(PlaylistId), 0) + 1 FROM Playlist")
        playlist_id = cur.fetchone()[0]
        cur.execute("INSERT INTO Playlist (PlaylistId, Name) VALUES (%s, %s)",
                    (playlist_id, name))
        cur.executemany("INSERT INTO PlaylistTrack (PlaylistId, TrackId) VALUES (%s, %s)",
                        [(playlist_id, t) for t in track_ids])

    cols, rows = fetch(
        "SELECT p.PlaylistId, p.Name AS Playlist, t.TrackId, t.Name AS Track "
        "FROM Playlist p JOIN PlaylistTrack pt ON pt.PlaylistId = p.PlaylistId "
        "JOIN Track t ON t.TrackId = pt.TrackId WHERE p.PlaylistId = %s", (playlist_id,))
    show(f'"{name}" created (PlaylistId {playlist_id})', cols, rows, "yellow")

    # Wrong order on purpose: the parent row is still referenced by PlaylistTrack
    try:
        with transaction() as cur:
            cur.execute("DELETE FROM Playlist WHERE PlaylistId = %s", (playlist_id,))
    except IntegrityError as exc:
        console.print(Panel(f"{exc.msg}", title="Parent-first delete rejected by MySQL",
                            border_style="red"))

    # Correct order: child rows first, then the parent row
    with transaction() as cur:
        cur.execute("DELETE FROM PlaylistTrack WHERE PlaylistId = %s", (playlist_id,))
        links = cur.rowcount
        cur.execute("DELETE FROM Playlist WHERE PlaylistId = %s", (playlist_id,))
        parents = cur.rowcount

    remaining = fetch_one("SELECT COUNT(*) FROM Playlist WHERE Name = %s", (name,))
    console.print(Panel(
        f"PlaylistTrack rows removed : {links}\n"
        f"Playlist rows removed      : {parents}\n"
        f"Playlists left with name   : {remaining}",
        title="Child-first delete completed", border_style="green"))


if __name__ == "__main__":
    preview_tracks()
    register_genre()
    reprice_genre()
    playlist_lifecycle()
