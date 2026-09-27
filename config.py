"""
App-wide constants: file paths, security parameters, and timing intervals.
Centralizing these here means changing a poll rate or file path doesn't
require hunting through app.py.
"""

DATA_FILE = "screentime_data.json"

# Password hashing
PBKDF2_ITERATIONS = 100_000

# Timers (all in milliseconds unless noted)
POLL_INTERVAL_MS = 250      # how often the limit-blocker checks the foreground app
THEME_POLL_MS = 15000       # how often "Match PC" re-checks the Windows theme setting
AUTOSAVE_MS = 30000         # background autosave cadence
UI_REFRESH_MS = 2000        # dashboard/statistics refresh cadence

HISTORY_RETENTION_DAYS = 90     # how many days of history are kept in the save file
DEFAULT_APP_LIMIT_MINUTES = 120  # default value shown when enabling a limit for an app
