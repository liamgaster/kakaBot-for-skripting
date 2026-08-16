# kakaBot-for-skripting 
 This bot is designed as an automated controller for Mist World, using NVDA's Speech Viewer as an accessibility-driven screen reading parser and a Flask-based web dashboard for remote management.
Core Functionality & Features
1. Game Automation & Movement
4-Directional Movement: Holds down movement keys (w, a, s, d) to traverse the game environment.
Smart Direction Policies: Automatically shifts movement patterns based on your selected policy:
Rotate: Cycles clockwise through directions (w  d  s  a).
Reverse: Instantly flips to the opposite direction (e.g., w  s).
Random: Chooses a non-active direction at random to overcome obstacles.
2. NVDA Speech Integration
Real-Time Text Scanning: Hooks directly into the NVDA Speech Viewer window to read in-game text, announcements, and events in real time.
Phrase Triggering (WHEN_SAID): Listens for specific spoken text and immediately fires automated reactions (e.g., changing movement direction when hitting a wall or obstacle).
3. Scriptable Execution Engine
Custom DSL Interpreter: Parses simple custom script commands to chain actions:
FOCUS GAME "Mist World" — Brings the game window to the foreground.
WAIT <ms> — Pauses execution for a set duration.
CLICK_UNTIL "phrase" — Repeatedly clicks the center of the window until NVDA detects a matching phrase.
HOLD <key> / RELEASE — Simulates physical key holds and releases using Windows hardware inputs (SendInput).
4. Web Control Dashboard & Multi-User Management
Local Web Interface: Serves a web dashboard running on [http://127.0.0.1:5000](http://127.0.0.1:5000).
User Authentication: Built-in SQLite database storing hashed passwords (werkzeug.security) for individual login and signup sessions.
Remote Engine Control: Allows you to edit scripts, change direction policies, and start or stop the engine directly from any web browser.
5. Emergency Controls & System Access
Global Hotkey Intercept: Listens for Ctrl+Shift+X to immediately kill active threads, release held keys, and halt the engine safely.
Administrative Privileges: Embeds Windows UAC elevation to allow direct hardware key and mouse injection into elevated game windows.
