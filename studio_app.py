"""
studio_app.py  |  Chinook Studio desktop application
-------------------------------------------------------------------
A Tkinter application styled with ttkbootstrap (runs fully offline).

Screens
  Sign-in      EmployeeId + password, verified against the salted SHA-256
               hash in Employee.Password. 3 wrong tries lock the form for 30 s.
  Dashboard    KPI cards, revenue share of the top genres, latest invoices.
  Catalogue    Treeview of tracks (TrackId, Name, Album Title, Genre, UnitPrice)
               live search by name / genre (partial match), and a track editor:
               add a track, update a price, delete a track
               (blocked when the track appears in InvoiceLine).
  Reports      choose a customer, preview their invoices, export them to CSV.

Run secure_setup.py once before launching this application.
"""

import csv
from decimal import Decimal, InvalidOperation
from tkinter import filedialog

import ttkbootstrap as tb
from mysql.connector import Error

from database import fetch, fetch_one, transaction
from secure_setup import verify

THEME = "superhero"
APP_NAME = "Chinook Studio"
LOCK_SECONDS = 30

TRACK_QUERY = """
    SELECT t.TrackId, t.Name, COALESCE(al.Title, '—'), COALESCE(g.Name, '—'), t.UnitPrice
    FROM Track t
    LEFT JOIN Album al ON al.AlbumId = t.AlbumId
    LEFT JOIN Genre g  ON g.GenreId  = t.GenreId
"""


# =============================================================================
# Small helpers for dialogs and notifications
# =============================================================================
def popup_info(parent, title, message):
    tb.Messagebox.show_info(message, title, parent=parent)


def popup_warning(parent, title, message):
    tb.Messagebox.show_warning(message, title, parent=parent)


def popup_error(parent, title, message):
    tb.Messagebox.show_error(message, title, parent=parent)


def ask_yes_no(parent, title, message):
    return tb.Messagebox.yesno(message, title, parent=parent, localize=False) == "Yes"


def toast(title, message, style="success"):
    """Small notification in the corner of the screen for 3 seconds."""
    tb.ToastNotification(title=title, message=message, duration=3000,
                         bootstyle=style).show_toast()


def money(value):
    return f"${value:,.2f}"


# =============================================================================
# 1. SIGN-IN SCREEN
# =============================================================================
class SignInView(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=0)
        self.app = app
        self.failures = 0

        card = tb.Frame(self, padding=40, bootstyle="secondary")
        card.place(relx=0.5, rely=0.5, anchor="center")

        tb.Label(card, text="♫", font=("Segoe UI", 40), bootstyle="inverse-secondary",
                 foreground="#4fc3f7").pack()
        tb.Label(card, text=APP_NAME, font=("Segoe UI", 24, "bold"),
                 bootstyle="inverse-secondary").pack()
        tb.Label(card, text="Staff sign-in · music store back office",
                 font=("Segoe UI", 10), bootstyle="inverse-secondary").pack(pady=(0, 24))

        self.emp_id = tb.StringVar()
        self.password = tb.StringVar()
        self.reveal = tb.BooleanVar(value=False)

        tb.Label(card, text="EMPLOYEE ID", font=("Segoe UI", 8, "bold"),
                 bootstyle="inverse-secondary").pack(anchor="w")
        self.id_entry = tb.Entry(card, textvariable=self.emp_id, width=34, font=("Segoe UI", 11))
        self.id_entry.pack(pady=(2, 12), ipady=4)

        tb.Label(card, text="PASSWORD", font=("Segoe UI", 8, "bold"),
                 bootstyle="inverse-secondary").pack(anchor="w")
        self.pw_entry = tb.Entry(card, textvariable=self.password, show="●", width=34,
                                 font=("Segoe UI", 11))
        self.pw_entry.pack(pady=(2, 6), ipady=4)
        tb.Checkbutton(card, text="Show password", variable=self.reveal,
                       bootstyle="info-round-toggle", command=self.toggle_reveal).pack(anchor="w")

        self.sign_in_btn = tb.Button(card, text="Sign in  →", bootstyle="info", width=32,
                                     command=self.sign_in)
        self.sign_in_btn.pack(pady=(20, 8), ipady=4)
        self.message = tb.Label(card, text="", bootstyle="inverse-secondary",
                                foreground="#ff6b6b", font=("Segoe UI", 9, "bold"))
        self.message.pack()

        self.id_entry.focus_set()
        app.bind("<Return>", lambda _e: self.sign_in())

    def toggle_reveal(self):
        self.pw_entry.configure(show="" if self.reveal.get() else "●")

    def sign_in(self):
        if str(self.sign_in_btn.cget("state")) == "disabled":
            return
        emp_text, password = self.emp_id.get().strip(), self.password.get()
        if not emp_text.isdigit() or not password:
            self.message.configure(text="Enter a numeric Employee ID and your password.")
            return
        try:
            _, rows = fetch("SELECT EmployeeId, FirstName, LastName, Title, Password "
                            "FROM Employee WHERE EmployeeId = %s", (int(emp_text),))
        except Error as exc:
            popup_error(self, "Database error", str(exc))
            return

        if rows and rows[0][4] and verify(password, rows[0][4]):
            emp_id, first, last, title, _ = rows[0]
            self.app.unbind("<Return>")
            self.app.open_workspace({"id": emp_id, "name": f"{first} {last}", "title": title})
            return

        # Same message for an unknown ID and a wrong password (no hints for attackers)
        self.failures += 1
        self.password.set("")
        if self.failures >= 3:
            self.lock(LOCK_SECONDS)
        else:
            self.message.configure(text=f"Invalid credentials · {3 - self.failures} attempt(s) left")

    def lock(self, seconds):
        """Disable the form for a while after three failed attempts."""
        if seconds <= 0:
            self.failures = 0
            self.sign_in_btn.configure(state="normal", text="Sign in  →")
            self.message.configure(text="You can try again now.")
            return
        self.sign_in_btn.configure(state="disabled", text=f"Locked · {seconds}s")
        self.message.configure(text="Too many failed attempts. Form locked.")
        self.after(1000, self.lock, seconds - 1)


# =============================================================================
# 2. WORKSPACE: sidebar + pages
# =============================================================================
class Workspace(tb.Frame):
    def __init__(self, app, user):
        super().__init__(app)
        self.app, self.user = app, user

        # ---- sidebar ----
        side = tb.Frame(self, bootstyle="dark", padding=(16, 20), width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tb.Label(side, text="♫  " + APP_NAME, font=("Segoe UI", 15, "bold"),
                 bootstyle="inverse-dark", foreground="#4fc3f7").pack(anchor="w", pady=(0, 28))

        self.nav_buttons = {}
        for key, label in [("dashboard", "▦   Dashboard"), ("catalogue", "♪   Track catalogue"),
                           ("reports", "▤   Customer reports")]:
            btn = tb.Button(side, text=label, bootstyle="dark", width=22,
                            command=lambda k=key: self.show(k))
            btn.pack(fill="x", pady=3, ipady=6)
            self.nav_buttons[key] = btn

        tb.Frame(side, bootstyle="dark").pack(fill="both", expand=True)
        tb.Separator(side, bootstyle="secondary").pack(fill="x", pady=10)
        tb.Label(side, text=user["name"], font=("Segoe UI", 11, "bold"),
                 bootstyle="inverse-dark").pack(anchor="w")
        tb.Label(side, text=user["title"], font=("Segoe UI", 9),
                 bootstyle="inverse-dark", foreground="#9aa5b1").pack(anchor="w", pady=(0, 10))
        tb.Button(side, text="Sign out", bootstyle="danger-outline",
                  command=app.sign_out).pack(fill="x")

        # ---- content area + status bar ----
        main = tb.Frame(self, padding=(24, 18))
        main.pack(side="left", fill="both", expand=True)
        self.status = tb.Label(main, text="Ready", foreground="#9fb3c8", font=("Segoe UI", 9))
        self.status.pack(side="bottom", anchor="w", pady=(10, 0))
        self.pages = {
            "dashboard": DashboardPage(main, self),
            "catalogue": CataloguePage(main, self),
            "reports": ReportsPage(main, self),
        }
        self.show("dashboard")

    def show(self, key):
        for name, page in self.pages.items():
            page.pack_forget()
            self.nav_buttons[name].configure(bootstyle="dark")
        self.nav_buttons[key].configure(bootstyle="info")
        self.pages[key].pack(fill="both", expand=True)
        self.pages[key].refresh()

    def set_status(self, text):
        self.status.configure(text=text)


def page_header(parent, title, subtitle):
    tb.Label(parent, text=title, font=("Segoe UI", 20, "bold")).pack(anchor="w")
    tb.Label(parent, text=subtitle, foreground="#9fb3c8").pack(anchor="w", pady=(0, 14))


def make_tree(parent, columns, widths, height=12, style="info"):
    """Treeview with a scrollbar and striped rows."""
    holder = tb.Frame(parent)
    tree = tb.Treeview(holder, columns=columns, show="headings", height=height, bootstyle=style)
    for col, width in zip(columns, widths):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="e" if col in ("TrackId", "UnitPrice", "Total", "InvoiceId") else "w")
    bar = tb.Scrollbar(holder, orient="vertical", command=tree.yview, bootstyle="round")
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    tree.tag_configure("stripe", background="#2b3e50")
    return holder, tree


# ----------------------------------------------------------------- dashboard
class DashboardPage(tb.Frame):
    def __init__(self, parent, workspace):
        super().__init__(parent)
        self.ws = workspace
        page_header(self, f"Welcome back, {workspace.user['name'].split()[0]}",
                    "Live overview of the Chinook music store")

        cards = tb.Frame(self)
        cards.pack(fill="x")
        self.kpis = {}
        for i, (key, label, style) in enumerate([("tracks", "TRACKS IN CATALOGUE", "info"),
                                                 ("customers", "CUSTOMERS", "success"),
                                                 ("invoices", "INVOICES", "warning"),
                                                 ("revenue", "TOTAL REVENUE", "danger")]):
            card = tb.Frame(cards, bootstyle=style, padding=(18, 14))
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            cards.columnconfigure(i, weight=1)
            value = tb.Label(card, text="…", font=("Segoe UI", 22, "bold"), bootstyle=f"inverse-{style}")
            value.pack(anchor="w")
            tb.Label(card, text=label, font=("Segoe UI", 8, "bold"),
                     bootstyle=f"inverse-{style}").pack(anchor="w")
            self.kpis[key] = value

        lower = tb.Frame(self)
        lower.pack(fill="both", expand=True, pady=(18, 0))
        lower.columnconfigure(0, weight=2)
        lower.columnconfigure(1, weight=3)

        self.genre_box = tb.Labelframe(lower, text=" Revenue share · top 5 genres ", padding=14,
                                       bootstyle="info")
        self.genre_box.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        recent = tb.Labelframe(lower, text=" Latest invoices ", padding=10, bootstyle="info")
        recent.grid(row=0, column=1, sticky="nsew")
        holder, self.recent_tree = make_tree(recent, ("InvoiceId", "Date", "Customer", "Country", "Total"),
                                             (70, 90, 150, 100, 70), height=14)
        holder.pack(fill="both", expand=True)

    def refresh(self):
        self.kpis["tracks"].configure(text=f"{fetch_one('SELECT COUNT(*) FROM Track'):,}")
        self.kpis["customers"].configure(text=f"{fetch_one('SELECT COUNT(*) FROM Customer'):,}")
        self.kpis["invoices"].configure(text=f"{fetch_one('SELECT COUNT(*) FROM Invoice'):,}")
        self.kpis["revenue"].configure(text=money(fetch_one('SELECT SUM(Total) FROM Invoice')))

        for child in self.genre_box.winfo_children():
            child.destroy()
        total = float(fetch_one("SELECT SUM(UnitPrice * Quantity) FROM InvoiceLine"))
        _, rows = fetch(
            "SELECT g.Name, SUM(il.UnitPrice * il.Quantity) AS revenue "
            "FROM InvoiceLine il JOIN Track t ON t.TrackId = il.TrackId "
            "JOIN Genre g ON g.GenreId = t.GenreId "
            "GROUP BY g.Name ORDER BY revenue DESC LIMIT %s", (5,))
        styles = ["info", "success", "warning", "danger", "primary"]
        for (name, revenue), style in zip(rows, styles):
            share = float(revenue) / total * 100
            line = tb.Frame(self.genre_box)
            line.pack(fill="x", pady=5)
            tb.Label(line, text=name, font=("Segoe UI", 10, "bold")).pack(side="left")
            tb.Label(line, text=f"{money(revenue)} · {share:.1f}%", foreground="#9fb3c8").pack(side="right")
            tb.Progressbar(self.genre_box, value=share, maximum=40,
                           bootstyle=f"{style}-striped").pack(fill="x")

        self.recent_tree.delete(*self.recent_tree.get_children())
        _, rows = fetch(
            "SELECT i.InvoiceId, DATE(i.InvoiceDate), CONCAT(c.FirstName, ' ', c.LastName), "
            "i.BillingCountry, i.Total FROM Invoice i JOIN Customer c ON c.CustomerId = i.CustomerId "
            "ORDER BY i.InvoiceDate DESC, i.InvoiceId DESC LIMIT %s", (14,))
        for n, (iid, date, cust, country, total_) in enumerate(rows):
            self.recent_tree.insert("", "end", values=(iid, date, cust, country, money(total_)),
                                    tags=("stripe",) if n % 2 else ())
        self.ws.set_status("Dashboard refreshed")


# ----------------------------------------------------------------- catalogue
class CataloguePage(tb.Frame):
    def __init__(self, parent, workspace):
        super().__init__(parent)
        self.ws = workspace
        self._search_job = None
        page_header(self, "Track catalogue", "Search, add, re-price and remove tracks")

        # ---- look-up lists for the dropdowns: label -> id ----
        self.albums = {f"{t}  (#{i})": i for i, t in fetch("SELECT AlbumId, Title FROM Album ORDER BY Title")[1]}
        self.genres = {n: i for i, n in fetch("SELECT GenreId, Name FROM Genre ORDER BY Name")[1]}
        self.media = {n: i for i, n in fetch("SELECT MediaTypeId, Name FROM MediaType ORDER BY Name")[1]}

        # ---- search toolbar ----
        bar = tb.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.query = tb.StringVar()
        search = tb.Entry(bar, textvariable=self.query, width=40, font=("Segoe UI", 10))
        search.pack(side="left", ipady=3)
        search.bind("<KeyRelease>", lambda _e: self.schedule_search())
        self.scope = tb.Combobox(bar, values=["Name or genre", "Track name", "Genre"],
                                 state="readonly", width=14, bootstyle="info")
        self.scope.current(0)
        self.scope.pack(side="left", padx=8)
        self.scope.bind("<<ComboboxSelected>>", lambda _e: self.search())
        tb.Button(bar, text="🔍 Search", bootstyle="info", command=self.search).pack(side="left")
        tb.Button(bar, text="Reset", bootstyle="secondary-outline", command=self.reset).pack(side="left", padx=6)
        tb.Button(bar, text="🗑 Delete selected", bootstyle="danger", command=self.delete_track).pack(side="left")
        self.counter = tb.Label(bar, text="", bootstyle="info", font=("Segoe UI", 10, "bold"))
        self.counter.pack(side="right")

        # ---- body: table (left) + editor (right) ----
        body = tb.Frame(self)
        body.pack(fill="both", expand=True)
        holder, self.tree = make_tree(body, ("TrackId", "Name", "Album Title", "Genre", "UnitPrice"),
                                      (70, 250, 220, 120, 80), height=16)
        holder.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        editor = tb.Labelframe(body, text=" Track editor ", padding=14, bootstyle="info")
        editor.pack(side="left", fill="y", padx=(14, 0))
        self.selected = tb.StringVar(value="New track")
        head = tb.Frame(editor)
        head.pack(fill="x", pady=(0, 8))
        tb.Label(head, textvariable=self.selected, font=("Segoe UI", 11, "bold"),
                 bootstyle="info").pack(side="left")
        tb.Button(head, text="Clear", bootstyle="info-outline",
                  command=self.clear).pack(side="right")

        self.fields = {}
        for key, label, kind in [("name", "Track name *", "entry"), ("album", "Album", self.albums),
                                 ("genre", "Genre", self.genres), ("media", "Media type *", self.media),
                                 ("composer", "Composer", "entry"), ("ms", "Duration (ms) *", "entry"),
                                 ("price", "Unit price ($) *", "entry")]:
            tb.Label(editor, text=label, font=("Segoe UI", 8, "bold")).pack(anchor="w")
            var = tb.StringVar()
            if kind == "entry":
                widget = tb.Entry(editor, textvariable=var, width=30)
            else:
                widget = tb.Combobox(editor, textvariable=var, values=list(kind), state="readonly", width=28)
            widget.pack(fill="x", pady=(1, 5))
            self.fields[key] = var

        tb.Button(editor, text="＋ Add track", bootstyle="success", command=self.add_track).pack(fill="x", pady=2)
        tb.Button(editor, text="✎ Update price", bootstyle="warning", command=self.update_price).pack(fill="x", pady=2)
        tb.Button(editor, text="🗑 Delete track", bootstyle="danger", command=self.delete_track).pack(fill="x", pady=2)

    # ---------- READ / SEARCH ----------
    def refresh(self):
        self.search()

    def load(self, rows):
        self.tree.delete(*self.tree.get_children())
        for n, (tid, name, album, genre, price) in enumerate(rows):
            self.tree.insert("", "end", iid=str(tid), values=(tid, name, album, genre, f"{price:.2f}"),
                             tags=("stripe",) if n % 2 else ())
        self.counter.configure(text=f"{len(rows):,} tracks")

    def schedule_search(self):
        """Live search: run the query 300 ms after the user stops typing."""
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(300, self.search)

    def search(self):
        text = self.query.get().strip()
        if not text:
            self.load(fetch(TRACK_QUERY + " ORDER BY t.TrackId")[1])
            self.ws.set_status("Showing the full catalogue")
            return
        pattern = f"%{text}%"
        scope = self.scope.get()
        if scope == "Track name":
            where, params = "WHERE t.Name LIKE %s", (pattern,)
        elif scope == "Genre":
            where, params = "WHERE g.Name LIKE %s", (pattern,)
        else:
            where, params = "WHERE t.Name LIKE %s OR g.Name LIKE %s", (pattern, pattern)
        rows = fetch(f"{TRACK_QUERY} {where} ORDER BY t.TrackId", params)[1]
        self.load(rows)
        self.ws.set_status(f'{len(rows)} match(es) for "{text}" in {scope.lower()}')

    def reset(self):
        self.query.set("")
        self.scope.current(0)
        self.search()

    # ---------- editor ----------
    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        _, rows = fetch("SELECT TrackId, Name, AlbumId, GenreId, MediaTypeId, Composer, Milliseconds, UnitPrice "
                        "FROM Track WHERE TrackId = %s", (int(sel[0]),))
        tid, name, album, genre, media, composer, ms, price = rows[0]
        label_of = lambda mapping, value: next((k for k, v in mapping.items() if v == value), "")
        self.selected.set(f"Editing track #{tid}")
        values = {"name": name, "album": label_of(self.albums, album), "genre": label_of(self.genres, genre),
                  "media": label_of(self.media, media), "composer": composer or "", "ms": str(ms),
                  "price": f"{price:.2f}"}
        for key, value in values.items():
            self.fields[key].set(value)

    def clear(self):
        for var in self.fields.values():
            var.set("")
        self.selected.set("New track")
        self.tree.selection_remove(*self.tree.selection())

    def read_price(self):
        try:
            price = Decimal(self.fields["price"].get().strip()).quantize(Decimal("0.01"))
            if price <= 0:
                raise InvalidOperation
            return price
        except InvalidOperation:
            popup_warning(self, "Invalid price", "Unit price must be a positive number, e.g. 1.29")
            return None

    # ---------- CREATE ----------
    def add_track(self):
        f = {k: v.get().strip() for k, v in self.fields.items()}
        if not f["name"] or not f["media"]:
            popup_warning(self, "Missing details", "Track name and media type are required.")
            return
        if not f["ms"].isdigit() or int(f["ms"]) <= 0:
            popup_warning(self, "Invalid duration", "Duration must be a whole number of milliseconds.")
            return
        price = self.read_price()
        if price is None:
            return
        try:
            with transaction() as cur:
                cur.execute("SELECT COALESCE(MAX(TrackId), 0) + 1 FROM Track FOR UPDATE")
                new_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO Track (TrackId, Name, AlbumId, MediaTypeId, GenreId, Composer, "
                    "Milliseconds, UnitPrice) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (new_id, f["name"], self.albums.get(f["album"]), self.media[f["media"]],
                     self.genres.get(f["genre"]), f["composer"] or None, int(f["ms"]), price))
        except Error as exc:
            popup_error(self, "Could not add track", str(exc))
            return
        self.reset()
        self.tree.selection_set(str(new_id))
        self.tree.see(str(new_id))
        self.ws.set_status(f'Track "{f["name"]}" added as #{new_id}')
        popup_info(self, "Track added", f'"{f["name"]}" was added to the catalogue as TrackId {new_id}.')

    # ---------- UPDATE ----------
    def update_price(self):
        sel = self.tree.selection()
        if not sel:
            popup_warning(self, "No track selected", "Select a track in the table first.")
            return
        price = self.read_price()
        if price is None:
            return
        track_id = int(sel[0])
        old = self.tree.item(sel[0], "values")[4]
        with transaction() as cur:
            cur.execute("UPDATE Track SET UnitPrice = %s WHERE TrackId = %s", (price, track_id))
        values = list(self.tree.item(sel[0], "values"))
        values[4] = f"{price:.2f}"
        self.tree.item(sel[0], values=values)
        self.ws.set_status(f"Track #{track_id} re-priced from ${old} to ${price}")
        popup_info(self, "Price updated", f"Track #{track_id}: ${old}  →  ${price}")

    # ---------- DELETE ----------
    def delete_track(self):
        sel = self.tree.selection()
        if not sel:
            popup_warning(self, "No track selected", "Select a track in the table first.")
            return
        track_id = int(sel[0])
        name = self.tree.item(sel[0], "values")[1]
        sold = fetch_one("SELECT COUNT(*) FROM InvoiceLine WHERE TrackId = %s", (track_id,))
        if sold:
            popup_warning(self, "Delete blocked",
                          f'"{name}" (#{track_id}) has been sold {sold} time(s).\n\n'
                          "Sold tracks must stay in the catalogue so that the\n"
                          "invoice history remains complete.")
            self.ws.set_status(f"Delete of #{track_id} blocked: track has sales")
            return
        if not ask_yes_no(self, "Delete track", f'Permanently delete "{name}" (#{track_id})?'):
            return
        with transaction() as cur:
            # PlaylistTrack references Track, so its rows are removed first
            cur.execute("DELETE FROM PlaylistTrack WHERE TrackId = %s", (track_id,))
            cur.execute("DELETE FROM Track WHERE TrackId = %s", (track_id,))
        self.tree.delete(sel[0])
        self.clear()
        self.counter.configure(text=f"{len(self.tree.get_children()):,} tracks")
        self.ws.set_status(f'Track "{name}" (#{track_id}) deleted')
        popup_info(self, "Track deleted", f'"{name}" (#{track_id}) was removed from the catalogue.')


# ----------------------------------------------------------------- reports
class ReportsPage(tb.Frame):
    def __init__(self, parent, workspace):
        super().__init__(parent)
        self.ws = workspace
        self.rows = []
        page_header(self, "Customer reports", "Preview a customer's invoices and export them to CSV")

        _, customers = fetch("SELECT CustomerId, FirstName, LastName, Country FROM Customer ORDER BY CustomerId")
        self.customers = {f"#{cid}  {fn} {ln} · {country}": cid for cid, fn, ln, country in customers}

        bar = tb.Frame(self)
        bar.pack(fill="x")
        self.choice = tb.Combobox(bar, values=list(self.customers), state="readonly", width=46, bootstyle="info")
        self.choice.pack(side="left", ipady=2)
        self.choice.bind("<<ComboboxSelected>>", lambda _e: self.preview())
        tb.Button(bar, text="⬇  Export to CSV", bootstyle="success", command=self.export).pack(side="left", padx=10)

        stats = tb.Frame(self)
        stats.pack(fill="x", pady=14)
        self.stat_labels = {}
        for i, (key, label, style) in enumerate([("count", "INVOICES", "info"), ("spend", "LIFETIME SPEND", "success"),
                                                 ("avg", "AVERAGE INVOICE", "warning")]):
            card = tb.Frame(stats, bootstyle=style, padding=(16, 10))
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            stats.columnconfigure(i, weight=1)
            value = tb.Label(card, text="—", font=("Segoe UI", 18, "bold"), bootstyle=f"inverse-{style}")
            value.pack(anchor="w")
            tb.Label(card, text=label, font=("Segoe UI", 8, "bold"), bootstyle=f"inverse-{style}").pack(anchor="w")
            self.stat_labels[key] = value

        holder, self.tree = make_tree(self, ("InvoiceId", "Date", "Address", "City", "Country", "Total"),
                                      (80, 100, 230, 140, 110, 80), height=12, style="success")
        holder.pack(fill="both", expand=True)

    def refresh(self):
        if not self.choice.get():
            self.ws.set_status("Choose a customer to preview their invoices")

    def preview(self):
        customer_id = self.customers[self.choice.get()]
        _, self.rows = fetch(
            "SELECT InvoiceId, DATE(InvoiceDate), BillingAddress, BillingCity, BillingCountry, Total "
            "FROM Invoice WHERE CustomerId = %s ORDER BY InvoiceDate", (customer_id,))
        self.tree.delete(*self.tree.get_children())
        for n, row in enumerate(self.rows):
            self.tree.insert("", "end", values=(*row[:5], money(row[5])), tags=("stripe",) if n % 2 else ())
        spend = sum(r[5] for r in self.rows)
        self.stat_labels["count"].configure(text=str(len(self.rows)))
        self.stat_labels["spend"].configure(text=money(spend))
        self.stat_labels["avg"].configure(text=money(spend / len(self.rows)) if self.rows else "—")
        self.ws.set_status(f"{len(self.rows)} invoice(s) loaded for customer #{customer_id}")

    def export(self):
        if not self.choice.get():
            popup_warning(self, "No customer", "Choose a customer first.")
            return
        customer_id = self.customers[self.choice.get()]
        path = filedialog.asksaveasfilename(
            parent=self, title="Export invoices", defaultextension=".csv",
            initialfile=f"customer_{customer_id}_invoices.csv", filetypes=[("CSV file", "*.csv")])
        if not path:
            return
        name = self.choice.get().split("  ", 1)[1].split(" · ")[0]
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["CustomerId", "CustomerName", "InvoiceId", "InvoiceDate",
                             "BillingAddress", "BillingCity", "BillingCountry", "Total"])
            for row in self.rows:
                writer.writerow([customer_id, name, *row])
        self.ws.set_status(f"Exported {len(self.rows)} invoice(s) to {path}")
        popup_info(self, "Export complete", f"{len(self.rows)} invoice(s) for {name} saved to:\n{path}")


# =============================================================================
# APPLICATION WINDOW
# =============================================================================
class StudioApp(tb.Window):
    def __init__(self):
        super().__init__(title=APP_NAME, themename=THEME, size=(1280, 780), minsize=(1100, 700))
        self.view = None
        style = tb.Style()
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        self.show_sign_in()

    def swap(self, view):
        if self.view is not None:
            self.view.destroy()
        self.view = view
        view.pack(fill="both", expand=True)

    def show_sign_in(self):
        self.title(f"{APP_NAME} · Sign in")
        self.swap(SignInView(self))

    def open_workspace(self, user):
        self.title(f"{APP_NAME} · {user['name']}")
        self.swap(Workspace(self, user))
        toast("Signed in", f"Welcome, {user['name']}", "info")

    def sign_out(self):
        if ask_yes_no(self, "Sign out", "Do you want to sign out?"):
            self.show_sign_in()


if __name__ == "__main__":
    StudioApp().mainloop()
