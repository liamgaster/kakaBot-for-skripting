# Compatibility shim for pkgutil.get_loader (removed in Python 3.14).
import importlib.util, pkgutil, types

if not hasattr(pkgutil, "get_loader"):
    def _get_loader(name_or_module):
        try:
            if isinstance(name_or_module, types.ModuleType):
                spec = getattr(name_or_module, "__spec__", None)
                if spec is None:
                    spec = importlib.util.find_spec(name_or_module.__name__)
            else:
                spec = importlib.util.find_spec(str(name_or_module))
            return spec.loader if spec else None
        except Exception:
            return None
    pkgutil.get_loader = _get_loader

import os
import sys
import threading
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

# Load Windows-only bot engine only if running on Windows
if sys.platform == "win32":
    try:
        from engine import BotEngine
    except ImportError:
        BotEngine = None
else:
    BotEngine = None

if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS  # PyInstaller temporary folder
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# DB setup
APPDATA_DIR = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "MistBot")
os.makedirs(APPDATA_DIR, exist_ok=True)
DB = os.path.join(APPDATA_DIR, "users.db")

# Flask init
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
app.secret_key = os.urandom(24)

# Simple sample DSL script
DEFAULT_SCRIPT = '''# Example script
FOCUS GAME "Mist World"
WAIT 500
CLICK_UNTIL "enemy"
HOLD w
WHEN_SAID "hit wall" : SWITCH_DIRECTION rotate
WHEN_SAID "mountain" : SWITCH_DIRECTION reverse
STOP_ON_HOTKEY ctrl+shift+x
'''

# Simple DB init
def init_db():
    if not os.path.exists(DB):
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("""CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE,
                        password_hash TEXT
                     )""")
        conn.commit()
        conn.close()

init_db()

# Global engine instance (one per run)
engine = None
engine_thread = None

@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if not username or not password:
            flash("Username and password required.")
            return redirect(url_for("signup"))
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password_hash) VALUES (?,?)",
                      (username, generate_password_hash(password)))
            conn.commit()
            conn.close()
            flash("Account created. Please log in.")
            return redirect(url_for("home"))
        except sqlite3.IntegrityError:
            flash("Username already exists.")
            conn.close()
            return redirect(url_for("signup"))
    return render_template("signup.html")

@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"].strip()
    password = request.form["password"]
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row and check_password_hash(row[0], password):
        session["user"] = username
        return redirect(url_for("dashboard"))
    flash("Invalid credentials")
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))

@app.route("/dashboard", methods=["GET","POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("home"))
    global engine, engine_thread
    if request.method == "POST":
        script_text = request.form.get("script_text", "")
        speech_title = request.form.get("speech_title", "NVDA - Speech Viewer")
        game_title = request.form.get("game_title", "Mist World")
        direction_policy = request.form.get("direction_policy", "rotate")
        start_cmd = request.form.get("start_cmd", "")
        
        if start_cmd == "start":
            if BotEngine is None:
                flash("Bot engine cannot run on Linux cloud servers. Run locally on Windows.")
            elif engine_thread and engine_thread.is_alive():
                flash("Engine already running")
            else:
                if engine is None:
                    engine = BotEngine(speech_window_title=speech_title, game_window_title=game_title)
                engine.set_direction_policy(direction_policy)
                engine.load_script(script_text)
                engine_thread = threading.Thread(target=engine.run, daemon=True)
                engine_thread.start()
                flash("Engine started")
        elif start_cmd == "stop":
            if engine:
                engine.stop()
                flash("Engine stop requested")

    return render_template("dashboard.html",
                           default_script=DEFAULT_SCRIPT,
                           speech_title="NVDA - Speech Viewer",
                           game_title="Mist World")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)