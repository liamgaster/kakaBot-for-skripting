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
from flask import Flask, jsonify, render_template, render_template_string, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

# Reserved usernames that cannot be registered publicly
RESERVED_USERNAMES = {"admin", "administrator", "root", "system", "moderator"}

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
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

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

# DB init with dynamic column migrations and default admin seeding
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    password_hash TEXT,
                    is_banned INTEGER DEFAULT 0,
                    is_admin INTEGER DEFAULT 0,
                    last_seen TIMESTAMP
                 )""")
    
    # Auto-migrate existing user databases missing new columns
    c.execute("PRAGMA table_info(users)")
    existing_cols = [col[1] for col in c.fetchall()]
    if "is_banned" not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    if "is_admin" not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    if "last_seen" not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN last_seen TIMESTAMP")

    # Seed default admin account if not already present
    c.execute("SELECT id FROM users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            ("admin", generate_password_hash("ChangeMeSecurePassword123!"))
        )
        
    conn.commit()
    conn.close()

init_db()

# Global engine instance (one per run)
engine = None
engine_thread = None

# Active script storage for API polling
active_bot_state = {
    "status": "stopped",
    "script": ""
}

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
            
        if username.lower() in RESERVED_USERNAMES:
            flash("This username is reserved and cannot be registered.")
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
    c.execute("SELECT password_hash, is_banned, is_admin FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    
    if row:
        if row[1] == 1:
            conn.close()
            flash("Your account is banned.")
            return redirect(url_for("home"))
            
        if check_password_hash(row[0], password):
            c.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE username = ?", (username,))
            conn.commit()
            conn.close()
            session["user"] = username
            session["is_admin"] = bool(row[2])
            return redirect(url_for("dashboard"))

    conn.close()
    flash("Invalid credentials")
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    session.pop("is_admin", None)
    return redirect(url_for("home"))

@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if "user" not in session:
        return redirect(url_for("home"))
        
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        username = session["user"]
        
        if not old_password or not new_password:
            flash("Both current and new passwords are required.")
            return redirect(url_for("change_password"))
            
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        
        if row and check_password_hash(row[0], old_password):
            c.execute("UPDATE users SET password_hash = ? WHERE username = ?", 
                      (generate_password_hash(new_password), username))
            conn.commit()
            conn.close()
            flash("Password changed successfully.")
            return redirect(url_for("dashboard"))
        else:
            conn.close()
            flash("Incorrect current password.")
            return redirect(url_for("change_password"))
            
    template = '''
    <!DOCTYPE html>
    <html>
    <head><title>Change Password</title></head>
    <body style="font-family: Arial; margin: 20px;">
        <h2>Change Password</h2>
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <ul style="color: red;">
            {% for message in messages %}
              <li>{{ message }}</li>
            {% endfor %}
            </ul>
          {% endif %}
        {% endwith %}
        <form method="POST">
            <label>Current Password:</label><br>
            <input type="password" name="old_password" required><br><br>
            <label>New Password:</label><br>
            <input type="password" name="new_password" required><br><br>
            <button type="submit">Update Password</button>
        </form>
        <br>
        <a href="{{ url_for('dashboard') }}">Back to Dashboard</a>
    </body>
    </html>
    '''
    return render_template_string(template)

# --- API ENDPOINTS FOR CLIENT APP ---

@app.route("/api/signup", methods=["POST"])
def api_signup():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"status": "error", "message": "Missing credentials"}), 400
        
    if username.lower() in RESERVED_USERNAMES:
        return jsonify({"status": "error", "message": "This username is reserved."}), 400

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password_hash) VALUES (?,?)",
                  (username, generate_password_hash(password)))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Account created!"})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "error", "message": "Username already exists."}), 409

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT password_hash, is_banned, is_admin FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    
    if row:
        if row[1] == 1:
            conn.close()
            return jsonify({"status": "error", "message": "Account is banned."}), 403
            
        if check_password_hash(row[0], password):
            c.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE username = ?", (username,))
            conn.commit()
            conn.close()
            return jsonify({
                "status": "success", 
                "message": "Logged in", 
                "is_admin": bool(row[2])
            })
            
    conn.close()
    return jsonify({"status": "error", "message": "Invalid username or password"}), 401

@app.route("/api/change_password", methods=["POST"])
def api_change_password():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")
    
    if not username or not old_password or not new_password:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400
        
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    
    if row and check_password_hash(row[0], old_password):
        c.execute("UPDATE users SET password_hash = ? WHERE username = ?", 
                  (generate_password_hash(new_password), username))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Password updated successfully"})
    else:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid username or current password"}), 401

@app.route("/api/heartbeat", methods=["POST"])
def api_heartbeat():
    """Client pings this endpoint to update online status and check for bans."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username required"}), 400

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE username = ?", (username,))
    row = c.fetchone()

    if row and row[0] == 1:
        conn.close()
        return jsonify({"status": "banned", "message": "User is banned"}), 403

    c.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/get_script", methods=["GET"])
def get_script():
    return jsonify(active_bot_state)

# --- ADMIN API ENDPOINTS FOR GUI CLIENT ---

@app.route("/api/admin/users", methods=["POST"])
def api_admin_users():
    """Returns all registered users for the desktop GUI admin panel."""
    data = request.get_json(silent=True) or {}
    admin_user = data.get("admin_username", "").strip()

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE username = ?", (admin_user,))
    row = c.fetchone()
    if not row or row[0] != 1:
        conn.close()
        return jsonify({"status": "error", "message": "Admin privileges required"}), 403

    c.execute("SELECT id, username, is_banned, is_admin, last_seen FROM users")
    users = [
        {
            "id": u[0],
            "username": u[1],
            "is_banned": bool(u[2]),
            "is_admin": bool(u[3]),
            "last_seen": u[4] or "Never"
        }
        for u in c.fetchall()
    ]
    conn.close()
    return jsonify({"status": "success", "users": users})

@app.route("/api/admin/ban", methods=["POST"])
def api_admin_ban():
    """Bans/kicks a target user by ID."""
    data = request.get_json(silent=True) or {}
    admin_user = data.get("admin_username", "").strip()
    target_id = data.get("target_id")

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE username = ?", (admin_user,))
    row = c.fetchone()
    if not row or row[0] != 1:
        conn.close()
        return jsonify({"status": "error", "message": "Admin privileges required"}), 403

    c.execute("UPDATE users SET is_banned = 1 WHERE id = ? AND is_admin = 0", (target_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "User banned successfully"})

@app.route("/api/admin/unban", methods=["POST"])
def api_admin_unban():
    """Unbans a target user by ID."""
    data = request.get_json(silent=True) or {}
    admin_user = data.get("admin_username", "").strip()
    target_id = data.get("target_id")

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE username = ?", (admin_user,))
    row = c.fetchone()
    if not row or row[0] != 1:
        conn.close()
        return jsonify({"status": "error", "message": "Admin privileges required"}), 403

    c.execute("UPDATE users SET is_banned = 0 WHERE id = ?", (target_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "User unbanned successfully"})

# --- WEB ADMIN PANEL ---

@app.route("/admin")
def admin_panel():
    if not session.get("is_admin"):
        flash("Access Denied: Admin privileges required.")
        return redirect(url_for("dashboard"))

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, username, is_banned, is_admin, last_seen FROM users")
    users = c.fetchall()
    conn.close()

    admin_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>MistBot Admin Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f9; }
            h2 { color: #333; }
            table { width: 100%; border-collapse: collapse; background: #fff; margin-top: 15px; }
            th, td { padding: 10px; border: 1px solid #ccc; text-align: left; }
            th { background-color: #eee; }
            .banned { color: red; font-weight: bold; }
            .active { color: green; font-weight: bold; }
            .btn { padding: 5px 10px; text-decoration: none; border-radius: 3px; }
            .btn-ban { background: #d9534f; color: white; }
            .btn-unban { background: #5cb85c; color: white; }
        </style>
    </head>
    <body>
        <h2>MistBot User Management</h2>
        <p><a href="{{ url_for('dashboard') }}">Back to Dashboard</a> | <a href="{{ url_for('logout') }}">Logout</a></p>
        <hr>
        <table>
            <tr>
                <th>ID</th>
                <th>Username</th>
                <th>Status</th>
                <th>Role</th>
                <th>Last Active (UTC)</th>
                <th>Action</th>
            </tr>
            {% for u in users %}
            <tr>
                <td>{{ u[0] }}</td>
                <td>{{ u[1] }}</td>
                <td>
                    {% if u[2] == 1 %}
                        <span class="banned">Banned</span>
                    {% else %}
                        <span class="active">Active</span>
                    {% endif %}
                </td>
                <td>{{ 'Admin' if u[3] == 1 else 'User' }}</td>
                <td>{{ u[4] if u[4] else 'Never' }}</td>
                <td>
                    {% if u[3] != 1 %}
                        {% if u[2] == 1 %}
                            <a href="{{ url_for('unban_user', user_id=u[0]) }}" class="btn btn-unban">Unban</a>
                        {% else %}
                            <a href="{{ url_for('ban_user', user_id=u[0]) }}" class="btn btn-ban">Ban / Kick</a>
                        {% endif %}
                    {% else %}
                        <i>Administrator</i>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
    </body>
    </html>
    """
    return render_template_string(admin_template, users=users)

@app.route("/admin/ban/<int:user_id>")
def ban_user(user_id):
    if not session.get("is_admin"):
        return "Access Denied", 403
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # Ensure superadmins cannot ban each other
    c.execute("UPDATE users SET is_banned = 1 WHERE id = ? AND is_admin = 0", (user_id,))
    conn.commit()
    conn.close()
    flash("User banned successfully.")
    return redirect(url_for("admin_panel"))

@app.route("/admin/unban/<int:user_id>")
def unban_user(user_id):
    if not session.get("is_admin"):
        return "Access Denied", 403
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("User unbanned successfully.")
    return redirect(url_for("admin_panel"))

# --- WEB DASHBOARD ---

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
            active_bot_state["status"] = "running"
            active_bot_state["script"] = script_text
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
            active_bot_state["status"] = "stopped"
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
