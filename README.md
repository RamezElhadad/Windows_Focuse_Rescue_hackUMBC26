# Windows Focus Rescue

Windows-only screen-time tracker with per-app daily limits and a foreground
blocker overlay.

## Setup

    pip install -r requirements.txt
    python main.py

## Layout

- `main.py` — entry point
- `config.py` — file paths, timing intervals, security constants
- `theme.py` — color palettes, dark/light/system mode resolution
- `process_utils.py` — Windows process discovery and naming
- `tracker.py` — background foreground-app time tracker (its own thread)
- `app.py` — the Tkinter window: tabs, parent-lock, and the limit blocker

`screentime_data.json` is created next to wherever you run the app from —
it stores history, per-app limits, the parent password hash, and the
appearance settings.

## Known limitations

- The system-process filter in `process_utils.py` is a hardcoded name list;
  it won't catch every Windows helper process.
- `close_blocked_app` terminates every process matching the app's name —
  e.g. all Chrome windows, not just the focused one.
- Wrong parent password fails silently (no error dialog) — by design in
  this version, but worth knowing if you're debugging "nothing happened."
