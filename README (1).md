# Windows Focus Rescue

A screen-time manager for Windows: tracks foreground app time, sets per-app
daily limits, and blocks an app with an overlay once its limit is hit.

Windows-only (uses `pywin32` and the Windows registry).

---

## Features

- **Foreground-only tracking** — counts time only when an app is focused
  and you're actually active (idle detection via last input time)
- **Per-app daily limits** — set individual minute limits, enabled per app
- **Blocking overlay** — covers the app when its limit is reached, with:
  - "+5 More Minutes" (requires the parent password)
  - "Close App"
- **Parent lock** — password-protected limit settings, hashed with salted PBKDF2
- **Theming** — Dark / Light / Match Windows, plus 11 color palettes
- **Statistics** — today / this week / this month totals, per-app breakdown

## Screenshots

> Add screenshots here after you take them

| Dashboard | App Limits | Tracking | Statistics |
|-----------|------------|----------|------------|
|           |            |          |            |

---

## Tech Stack

- Python 3.10+
- Tkinter + `ttk`
- `psutil` — process monitoring
- `pywin32` — foreground window detection
- Windows Registry — installed-apps list, system theme detection

---

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/windows-focus-rescue.git
cd windows-focus-rescue
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

(Replace the clone URL once this actually has a repo home.)

---

## Project Structure

```text
windows-focus-rescue/
├── main.py             # Entry point
├── config.py           # File paths, timing intervals, security constants
├── theme.py            # Palettes + dark/light/system mode resolution
├── process_utils.py    # Windows process discovery and naming
├── tracker.py          # AppTimeTracker — background foreground-time tracker
├── app.py              # ScreenTimeApp — window, tabs, parent-lock, blocker overlay
├── requirements.txt
├── README.md
└── screentime_data.json  # auto-generated on first run
```

---

## How to Use

1. **Set a parent password** — Dashboard → "Who is using the PC"
2. **Set app limits** — App Limits tab (parent password required), enable an
   app, set its daily minute limit
3. **Track usage** — Tracking tab shows live foreground time and running apps
4. **View stats** — Statistics tab shows daily/weekly/monthly totals and
   per-app limit status
5. **When a limit is hit** — a blocking overlay appears over that app's window

---

## Data & Privacy

- All data is stored locally in `screentime_data.json` — nothing is sent
  anywhere
- History is retained for the last 90 days
- The "today" bucket is keyed by calendar date, but there's no active
  midnight rollover — see Known Limitations below

---

## Known Limitations

- **No midnight reset while the app is running.** The tracker doesn't split
  time at midnight; if the app stays open overnight, time can be misattributed
  to the wrong day until the app restarts. Don't rely on "daily" limits being
  exact if you never close the app.
- **`Close App` closes every process matching that name** — e.g. all Chrome
  windows, not just the one that was focused and blocked.
- **System-process filtering is a hardcoded name list** in `process_utils.py`
  — it won't catch every Windows helper process, and may occasionally list
  one as if it were a trackable app.
- **Wrong parent password fails silently** — no error dialog, just no unlock.
  Useful to know if you're debugging "nothing happened."
- Blocking is per-window overlay, not a system-wide lock — closing/reopening
  fast enough, or a second window of the same app, isn't covered instantly.
- Some UWP/Microsoft Store apps may not resolve cleanly in the installed-apps
  list (registry-based lookup).

---

## Contributing

Pull requests welcome. For anything nontrivial, open an issue first.

## License

No LICENSE file is included yet. Add one (e.g. MIT) before treating this as
open source — a README claim isn't a license grant on its own.

---

**Made with focus** — Windows Focus Rescue
