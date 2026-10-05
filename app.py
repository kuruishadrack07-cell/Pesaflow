import os
import sqlite3
import secrets
import random
import string
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, render_template, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.environ.get("DATA_DIR", BASE_DIR), "pesaflow.db")

app = Flask(__name__, static_folder="static", template_folder="templates")

SEND_TIERS = [
    (100, 0), (500, 7), (1000, 13), (1500, 23), (2500, 33),
    (3500, 53), (5000, 57), (7500, 78), (10000, 90),
    (15000, 100), (20000, 105), (float("inf"), 108),
]
WITHDRAW_TIERS = [
    (100, 11), (500, 29), (1000, 29), (1500, 29), (2500, 29),
    (3500, 52), (5000, 69), (7500, 87), (10000, 115),
    (15000, 167), (20000, 185), (float("inf"), 197),
]
MIN_AMOUNT = 1.0
MAX_AMOUNT = 150000.0


def tier_fee(amount, tiers):
    for cap, fee in tiers:
        if amount <= cap:
            return float(fee)
    return float(tiers[-1][1])


def get_db():
    if "db" not in g:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    pin_hash TEXT NOT NULL,
    balance REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    counterparty_name TEXT,
    counterparty_phone TEXT,
    note TEXT,
    balance_after REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    kind TEXT NOT NULL DEFAULT 'info',
    read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ref TEXT,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    kind TEXT NOT NULL
);
"""

AGENTS = [
    ("Mama Njeri Shop", "Kimathi Street, Nairobi", "agent"),
    ("Sunrise Pharmacy", "Tom Mboya Street, Nairobi", "agent"),
    ("QuickMart Express", "Ngong Road, Nairobi", "agent"),
    ("Equity Agent - Kenyatta Ave", "Kenyatta Avenue, Nairobi", "bank"),
    ("KCB Mtaani - Moi Ave", "Moi Avenue, Nairobi", "bank"),
    ("PesaPoint ATM", "Hilton Hotel, CBD", "atm"),
]

DEMO_USERS = [
    ("Amina Wanjiru", "0712345678", "1234", 12450.75),
    ("Brian Otieno", "0722111222", "1234", 3200.00),
    ("Cynthia Mwangi", "0733444555", "1234", 8750.50),
]


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def new_ref():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choices(alphabet, k=10))


def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()

    if conn.execute("SELECT COUNT(*) AS c FROM agents").fetchone()["c"] == 0:
        conn.executemany(
            "INSERT INTO agents (name, location, kind) VALUES (?, ?, ?)", AGENTS
        )

    if conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
        for name, phone, pin, balance in DEMO_USERS:
            conn.execute(
                "INSERT INTO users (name, phone, pin_hash, balance, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, phone, generate_password_hash(pin), balance, now()),
            )
        conn.commit()

        amina = conn.execute("SELECT id, balance FROM users WHERE phone = ?",
                             ("0712345678",)).fetchone()
        seed_tx = [
            ("deposit", 5000, 0, "Mama Njeri Shop", None, "Cash deposit"),
            ("send_out", 1200, 13, "Brian Otieno", "0722111222", "Rent top-up"),
            ("send_in", 2500, 0, "Cynthia Mwangi", "0733444555", "Lunch split"),
            ("withdraw", 1000, 29, "PesaPoint ATM", None, None),
        ]
        running = amina["balance"]
        for ttype, amount, fee, cp_name, cp_phone, note in seed_tx:
            ref = new_ref()
            conn.execute(
                "INSERT INTO transactions (ref, user_id, type, amount, fee, "
                "counterparty_name, counterparty_phone, note, balance_after, "
                "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?)",
                (ref, amina["id"], ttype, amount, fee, cp_name, cp_phone,
                 note, running, now()),
            )
        conn.execute(
            "INSERT INTO notifications (user_id, title, body, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (amina["id"], "Welcome to PesaFlow",
             "Your wallet is ready. Deposit cash with any agent to get started.",
             "info", now()),
        )
        conn.commit()

    conn.close()


def normalize_phone(raw):
    if not raw:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if digits.startswith("254"):
        digits = "0" + digits[3:]
    if len(digits) == 9 and digits[0] in ("7", "1"):
        digits = "0" + digits
    if len(digits) == 10 and digits[0] == "0" and digits[1] in ("7", "1"):
        return digits
    return None


def valid_pin(pin):
    return isinstance(pin, str) and len(pin) == 4 and pin.isdigit()


def user_public(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "phone": row["phone"],
        "balance": round(row["balance"], 2),
        "created_at": row["created_at"],
    }


def tx_public(row):
    return {
        "ref": row["ref"],
        "type": row["type"],
        "amount": round(row["amount"], 2),
        "fee": round(row["fee"], 2),
        "counterparty_name": row["counterparty_name"],
        "counterparty_phone": row["counterparty_phone"],
        "note": row["note"],
        "balance_after": round(row["balance_after"], 2),
        "status": row["status"],
        "created_at": row["created_at"],
    }


def notify(db, user_id, title, body="", kind="info"):
    db.execute(
        "INSERT INTO notifications (user_id, title, body, kind, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, title, body, kind, now()),
    )


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header.replace("Bearer ", "").strip()
        if not token:
            return jsonify(error="Missing authentication token"), 401
        db = get_db()
        row = db.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ?", (token,)
        ).fetchone()
        if not row:
            return jsonify(error="Session expired. Please sign in again."), 401
        g.current_user = row
        return fn(*args, **kwargs)
    return wrapper


def parse_amount(raw):
    try:
        amt = float(raw)
    except (TypeError, ValueError):
        return None
    if amt <= 0:
        return None
    return round(amt, 2)


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True, time=now())


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = normalize_phone(data.get("phone"))
    pin = str(data.get("pin") or "")
    pin2 = str(data.get("pin2") or pin)

    if len(name) < 3:
        return jsonify(error="Please enter your full name."), 400
    if not phone:
        return jsonify(error="Enter a valid Kenyan phone number."), 400
    if not valid_pin(pin):
        return jsonify(error="PIN must be exactly 4 digits."), 400
    if pin != pin2:
        return jsonify(error="PINs do not match."), 400

    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE phone = ?", (phone,)).fetchone():
        return jsonify(error="That phone number is already registered."), 409

    cur = db.execute(
        "INSERT INTO users (name, phone, pin_hash, balance, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (name, phone, generate_password_hash(pin), now()),
    )
    user_id = cur.lastrowid
    notify(db, user_id, "Welcome to PesaFlow",
           "Your wallet is ready. Deposit cash with any agent to get started.")
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
               (token, user_id, now()))
    db.commit()

    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return jsonify(token=token, user=user_public(user)), 201


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    phone = normalize_phone(data.get("phone"))
    pin = str(data.get("pin") or "")

    if not phone or not valid_pin(pin):
        return jsonify(error="Enter your phone number and 4-digit PIN."), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    if not user or not check_password_hash(user["pin_hash"], pin):
        return jsonify(error="Incorrect phone number or PIN."), 401

    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
               (token, user["id"], now()))
    db.commit()
    return jsonify(token=token, user=user_public(user))


@app.post("/api/logout")
@require_auth
def logout():
    header = request.headers.get("Authorization", "")
    token = header.replace("Bearer ", "").strip()
    db = get_db()
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    db.commit()
    return jsonify(ok=True)


@app.get("/api/me")
@require_auth
def me():
    return jsonify(user=user_public(g.current_user))


@app.post("/api/change-pin")
@require_auth
def change_pin():
    data = request.get_json(silent=True) or {}
    old = str(data.get("old_pin") or "")
    new = str(data.get("new_pin") or "")

    if not valid_pin(new):
        return jsonify(error="New PIN must be 4 digits."), 400
    if not check_password_hash(g.current_user["pin_hash"], old):
        return jsonify(error="Current PIN is incorrect."), 401

    db = get_db()
    db.execute("UPDATE users SET pin_hash = ? WHERE id = ?",
               (generate_password_hash(new), g.current_user["id"]))
    notify(db, g.current_user["id"], "PIN changed",
           "Your PesaFlow PIN was updated successfully.")
    db.commit()
    return jsonify(ok=True)


@app.get("/api/lookup")
@require_auth
def lookup():
    phone = normalize_phone(request.args.get("phone"))
    if not phone:
        return jsonify(error="Invalid phone number."), 400
    if phone == g.current_user["phone"]:
        return jsonify(error="You cannot send money to yourself."), 400

    db = get_db()
    user = db.execute("SELECT name FROM users WHERE phone = ?", (phone,)).fetchone()
    if not user:
        return jsonify(error="That number is not on PesaFlow yet."), 404
    return jsonify(name=user["name"], phone=phone)


@app.get("/api/fees")
def fees():
    amount = parse_amount(request.args.get("amount")) or 0
    return jsonify(
        send_fee=tier_fee(amount, SEND_TIERS),
        withdraw_fee=tier_fee(amount, WITHDRAW_TIERS),
        min=MIN_AMOUNT,
        max=MAX_AMOUNT,
    )


@app.get("/api/agents")
@require_auth
def agents():
    db = get_db()
    rows = db.execute("SELECT * FROM agents ORDER BY kind, name").fetchall()
    return jsonify(agents=[dict(r) for r in rows])


@app.post("/api/deposit")
@require_auth
def deposit():
    data = request.get_json(silent=True) or {}
    amount = parse_amount(data.get("amount"))
    agent_id = data.get("agent_id")

    if amount is None or amount < MIN_AMOUNT:
        return jsonify(error=f"Enter an amount of at least KES {MIN_AMOUNT:.0f}."), 400
    if amount > MAX_AMOUNT:
        return jsonify(error=f"Maximum deposit is KES {MAX_AMOUNT:,.0f}."), 400

    db = get_db()
    agent = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not agent:
        return jsonify(error="Select a deposit agent."), 400

    new_balance = round(g.current_user["balance"] + amount, 2)
    ref = new_ref()
    db.execute("UPDATE users SET balance = ? WHERE id = ?",
               (new_balance, g.current_user["id"]))
    db.execute(
        "INSERT INTO transactions (ref, user_id, type, amount, fee, counterparty_name, "
        "counterparty_phone, note, balance_after, status, created_at) "
        "VALUES (?, ?, 'deposit', ?, 0, ?, NULL, ?, ?, 'completed', ?)",
        (ref, g.current_user["id"], amount, agent["name"],
         f"Cash deposit at {agent['name']}", new_balance, now()),
    )
    notify(db, g.current_user["id"], "Deposit confirmed",
           f"KES {amount:,.2f} received from {agent['name']}. Ref {ref}.", "in")
    db.commit()

    user = db.execute("SELECT * FROM users WHERE id = ?",
                      (g.current_user["id"],)).fetchone()
    tx = db.execute("SELECT * FROM transactions WHERE ref = ?", (ref,)).fetchone()
    return jsonify(user=user_public(user), transaction=tx_public(tx))


@app.post("/api/withdraw")
@require_auth
def withdraw():
    data = request.get_json(silent=True) or {}
    amount = parse_amount(data.get("amount"))
    agent_id = data.get("agent_id")
    pin = str(data.get("pin") or "")

    if not check_password_hash(g.current_user["pin_hash"], pin):
        return jsonify(error="Incorrect PIN."), 401
    if amount is None or amount < MIN_AMOUNT:
        return jsonify(error=f"Enter an amount of at least KES {MIN_AMOUNT:.0f}."), 400
    if amount > MAX_AMOUNT:
        return jsonify(error=f"Maximum withdrawal is KES {MAX_AMOUNT:,.0f}."), 400

    db = get_db()
    agent = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not agent:
        return jsonify(error="Select a withdrawal agent."), 400

    fee = tier_fee(amount, WITHDRAW_TIERS)
    total = round(amount + fee, 2)
    if total > g.current_user["balance"]:
        return jsonify(error="Insufficient balance for this withdrawal."), 400

    new_balance = round(g.current_user["balance"] - total, 2)
    ref = new_ref()
    db.execute("UPDATE users SET balance = ? WHERE id = ?",
               (new_balance, g.current_user["id"]))
    db.execute(
        "INSERT INTO transactions (ref, user_id, type, amount, fee, counterparty_name, "
        "counterparty_phone, note, balance_after, status, created_at) "
        "VALUES (?, ?, 'withdraw', ?, ?, ?, NULL, ?, ?, 'completed', ?)",
        (ref, g.current_user["id"], amount, fee, agent["name"],
         f"Withdrawal at {agent['name']}", new_balance, now()),
    )
    notify(db, g.current_user["id"], "Withdrawal successful",
           f"You withdrew KES {amount:,.2f} at {agent['name']}. Ref {ref}.", "out")
    db.commit()

    user = db.execute("SELECT * FROM users WHERE id = ?",
                      (g.current_user["id"],)).fetchone()
    tx = db.execute("SELECT * FROM transactions WHERE ref = ?", (ref,)).fetchone()
    return jsonify(user=user_public(user), transaction=tx_public(tx))


@app.post("/api/send")
@require_auth
def send():
    data = request.get_json(silent=True) or {}
    amount = parse_amount(data.get("amount"))
    phone = normalize_phone(data.get("phone"))
    note = (data.get("note") or "").strip()[:60] or None
    pin = str(data.get("pin") or "")

    if not check_password_hash(g.current_user["pin_hash"], pin):
        return jsonify(error="Incorrect PIN."), 401
    if amount is None or amount < MIN_AMOUNT:
        return jsonify(error=f"Enter an amount of at least KES {MIN_AMOUNT:.0f}."), 400
    if amount > MAX_AMOUNT:
        return jsonify(error=f"Maximum send amount is KES {MAX_AMOUNT:,.0f}."), 400
    if not phone:
        return jsonify(error="Enter a valid recipient phone number."), 400
    if phone == g.current_user["phone"]:
        return jsonify(error="You cannot send money to yourself."), 400

    db = get_db()
    recipient = db.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    if not recipient:
        return jsonify(error="That number is not registered on PesaFlow."), 404

    fee = tier_fee(amount, SEND_TIERS)
    total = round(amount + fee, 2)
    if total > g.current_user["balance"]:
        return jsonify(error="Insufficient balance for this transaction."), 400

    sender_balance = round(g.current_user["balance"] - total, 2)
    recipient_balance = round(recipient["balance"] + amount, 2)
    ref_out = new_ref()
    ref_in = new_ref()

    db.execute("UPDATE users SET balance = ? WHERE id = ?",
               (sender_balance, g.current_user["id"]))
    db.execute("UPDATE users SET balance = ? WHERE id = ?",
               (recipient_balance, recipient["id"]))

    db.execute(
        "INSERT INTO transactions (ref, user_id, type, amount, fee, counterparty_name, "
        "counterparty_phone, note, balance_after, status, created_at) "
        "VALUES (?, ?, 'send_out', ?, ?, ?, ?, ?, ?, 'completed', ?)",
        (ref_out, g.current_user["id"], amount, fee, recipient["name"], phone,
         note, sender_balance, now()),
    )
    db.execute(
        "INSERT INTO transactions (ref, user_id, type, amount, fee, counterparty_name, "
        "counterparty_phone, note, balance_after, status, created_at) "
        "VALUES (?, ?, 'send_in', ?, 0, ?, ?, ?, ?, 'completed', ?)",
        (ref_in, recipient["id"], amount, g.current_user["name"],
         g.current_user["phone"], note, recipient_balance, now()),
    )

    notify(db, g.current_user["id"], "Money sent",
           f"KES {amount:,.2f} sent to {recipient['name']} ({phone}). Ref {ref_out}.",
           "out")
    notify(db, recipient["id"], "Money received",
           f"KES {amount:,.2f} from {g.current_user['name']} "
           f"({g.current_user['phone']}). Ref {ref_in}.", "in")
    db.commit()

    user = db.execute("SELECT * FROM users WHERE id = ?",
                      (g.current_user["id"],)).fetchone()
    tx = db.execute("SELECT * FROM transactions WHERE ref = ?", (ref_out,)).fetchone()
    return jsonify(user=user_public(user), transaction=tx_public(tx))


@app.post("/api/simulate-incoming")
@require_auth
def simulate_incoming():
    db = get_db()
    senders = db.execute(
        "SELECT * FROM users WHERE id != ? ORDER BY RANDOM() LIMIT 1",
        (g.current_user["id"],)
    ).fetchall()
    if not senders:
        return jsonify(error="No other users to simulate from."), 400
    sender = senders[0]

    amount = round(random.uniform(50, 1500), 2)
    ref = new_ref()
    new_balance = round(g.current_user["balance"] + amount, 2)
    db.execute("UPDATE users SET balance = ? WHERE id = ?",
               (new_balance, g.current_user["id"]))
    db.execute(
        "INSERT INTO transactions (ref, user_id, type, amount, fee, counterparty_name, "
        "counterparty_phone, note, balance_after, status, created_at) "
        "VALUES (?, ?, 'send_in', ?, 0, ?, ?, ?, ?, 'completed', ?)",
        (ref, g.current_user["id"], amount, sender["name"], sender["phone"],
         "Incoming payment (demo)", new_balance, now()),
    )
    notify(db, g.current_user["id"], "Money received",
           f"KES {amount:,.2f} from {sender['name']}. Ref {ref}.", "in")
    db.commit()

    user = db.execute("SELECT * FROM users WHERE id = ?",
                      (g.current_user["id"],)).fetchone()
    tx = db.execute("SELECT * FROM transactions WHERE ref = ?", (ref,)).fetchone()
    return jsonify(user=user_public(user), transaction=tx_public(tx))


@app.get("/api/transactions")
@require_auth
def transactions():
    kind = request.args.get("filter", "all")
    db = get_db()

    query = "SELECT * FROM transactions WHERE user_id = ?"
    params = [g.current_user["id"]]

    if kind == "in":
        query += " AND type IN ('send_in', 'deposit')"
    elif kind == "out":
        query += " AND type IN ('send_out', 'withdraw')"
    elif kind == "send":
        query += " AND type = 'send_out'"
    elif kind == "withdraw":
        query += " AND type = 'withdraw'"
    elif kind == "deposit":
        query += " AND type = 'deposit'"

    query += " ORDER BY id DESC LIMIT 100"
    rows = db.execute(query, params).fetchall()
    return jsonify(transactions=[tx_public(r) for r in rows])


@app.get("/api/transactions/<ref>")
@require_auth
def transaction_detail(ref):
    db = get_db()
    row = db.execute(
        "SELECT * FROM transactions WHERE ref = ? AND user_id = ?",
        (ref, g.current_user["id"])
    ).fetchone()
    if not row:
        return jsonify(error="Transaction not found."), 404
    return jsonify(transaction=tx_public(row))


@app.get("/api/notifications")
@require_auth
def notifications():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 50",
        (g.current_user["id"],)
    ).fetchall()
    unread = db.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND read = 0",
        (g.current_user["id"],)
    ).fetchone()["c"]
    return jsonify(
        notifications=[
            {"id": r["id"], "title": r["title"], "body": r["body"],
             "kind": r["kind"], "read": bool(r["read"]), "created_at": r["created_at"]}
            for r in rows
        ],
        unread=unread,
    )


@app.post("/api/notifications/read")
@require_auth
def mark_notifications_read():
    db = get_db()
    db.execute("UPDATE notifications SET read = 1 WHERE user_id = ?",
               (g.current_user["id"],))
    db.commit()
    return jsonify(ok=True)


@app.post("/api/support")
@require_auth
def create_ticket():
    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()
    ref = (data.get("ref") or "").strip() or None

    if len(subject) < 3:
        return jsonify(error="Please add a short subject."), 400
    if len(message) < 10:
        return jsonify(error="Please describe the issue in a bit more detail."), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO tickets (user_id, ref, subject, message, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (g.current_user["id"], ref, subject, message, now()),
    )
    db.commit()
    row = db.execute("SELECT * FROM tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(ticket={
        "id": row["id"], "ref": row["ref"], "subject": row["subject"],
        "message": row["message"], "status": row["status"],
        "created_at": row["created_at"],
    }), 201


@app.get("/api/support")
@require_auth
def list_tickets():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM tickets WHERE user_id = ? ORDER BY id DESC",
        (g.current_user["id"],)
    ).fetchall()
    return jsonify(tickets=[
        {"id": r["id"], "ref": r["ref"], "subject": r["subject"],
         "message": r["message"], "status": r["status"], "created_at": r["created_at"]}
        for r in rows
    ])


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
