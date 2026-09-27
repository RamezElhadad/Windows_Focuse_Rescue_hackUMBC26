"""
Main application: window, tabs, theming glue, parent-lock, and the
foreground app-limit blocker. This is the biggest module by design —
tkinter's callback-heavy style ties nearly every method to `self`, so
splitting ScreenTimeApp itself across files would mean either a mixin
soup or passing a lot of shared state through constructor args for
little real benefit. The other concerns (theme, process lookups,
tracking, constants) are already factored out into their own modules.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import json
import os
import secrets
import hashlib
import threading
from datetime import timedelta, date, timedelta as td

import psutil
import win32gui
import win32process

from config import (
    DATA_FILE, PBKDF2_ITERATIONS, POLL_INTERVAL_MS, THEME_POLL_MS,
    AUTOSAVE_MS, UI_REFRESH_MS, HISTORY_RETENTION_DAYS, DEFAULT_APP_LIMIT_MINUTES,
)
from theme import COLORS, PALETTES, shade, resolve_colors, get_system_theme
from process_utils import clean_name, friendly_name, is_system, get_installed_apps
from tracker import AppTimeTracker


class ScreenTimeApp:
    MODE_DISPLAY = {"dark": "Dark", "light": "Light", "system": "Match PC"}

    def __init__(self, root):
        self.root = root
        self.root.title("Windows Focus Rescue")
        self.root.geometry("1020x820")
        self.root.minsize(880, 700)

        self.parent_password_hash = None
        self.is_parent_unlocked = False
        self.app_limits = {}
        self.history = {}
        self.installed = {}
        self.selected = set()
        self.theme_mode = "system"
        self.palette_name = "Original"

        # ---------- APP LIMIT BLOCKER ----------
        self.overlay = None
        self.overlay_target_hwnd = None
        self.overlay_target_app = None

        # Temporary extra time granted from the blocker overlay.
        # This is intentionally not saved, so the normal daily limit stays unchanged.
        self.extra_time = {}

        self.tracker = AppTimeTracker()
        self.load()
        self.tracker.start()

        self.apply_theme()
        self._last_resolved_mode = self.effective_mode()

        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.auto_save()
        self.update_ui()
        self.check_app_limits()
        self._poll_system_theme()
        threading.Thread(target=self._load_installed, daemon=True).start()

    # ---------- THEME ----------
    def effective_mode(self) -> str:
        return get_system_theme() if self.theme_mode == "system" else self.theme_mode

    def apply_theme(self):
        COLORS.clear()
        COLORS.update(resolve_colors(self.effective_mode(), self.palette_name))

    def on_theme_setting_changed(self):
        self.apply_theme()
        self._last_resolved_mode = self.effective_mode()
        self.save()
        self._build_ui(rebuilding=True)

    def _poll_system_theme(self):
        if self.theme_mode == "system":
            resolved = get_system_theme()
            if resolved != self._last_resolved_mode:
                self._last_resolved_mode = resolved
                self.apply_theme()
                self._build_ui(rebuilding=True)
        self.root.after(THEME_POLL_MS, self._poll_system_theme)

    def _build_ui(self, rebuilding=False):
        if rebuilding:
            try:
                current_tab = self.nb.index(self.nb.select())
            except Exception:
                current_tab = 0
            for w in self.root.winfo_children():
                w.destroy()
        else:
            current_tab = 0

        self.root.configure(bg=COLORS["bg"])
        self.setup_styles()
        self.build_header()
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=14, pady=10)

        self.init_dashboard()
        self.init_limits()
        self.init_tracking()
        self.init_statistics()

        self.status = tk.Label(self.root, text=" Ready", anchor="w", padx=12, pady=5,
                               bg=COLORS["card2"], fg=COLORS["text_dim"], font=("Segoe UI", 9))
        self.status.pack(fill="x", side="bottom")

        if rebuilding:
            try:
                self.nb.select(current_tab)
            except Exception:
                pass
            if self.is_parent_unlocked:
                self.refresh_limits()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=COLORS["card2"],
                        foreground=COLORS["text_dim"],
                        padding=[18, 10],
                        font=("Segoe UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", COLORS["card"])],
                  foreground=[("selected", COLORS["accent"])])

        style.configure("TFrame", background=COLORS["bg"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("TButton",
                        background=COLORS["card2"],
                        foreground=COLORS["text"],
                        font=("Segoe UI", 10),
                        padding=7,
                        borderwidth=0)
        style.map("TButton",
                  background=[("active", COLORS["accent"])],
                  foreground=[("active", "#ffffff")])

        style.configure("Accent.TButton",
                        background=COLORS["accent"],
                        foreground="#ffffff",
                        font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", shade(COLORS["accent"], 0.85))])

        style.configure("Treeview",
                        background=COLORS["card"],
                        foreground=COLORS["text"],
                        fieldbackground=COLORS["card"],
                        rowheight=27,
                        font=("Segoe UI", 10),
                        borderwidth=0)
        style.configure("Treeview.Heading",
                        background=COLORS["card2"],
                        foreground=COLORS["accent"],
                        font=("Segoe UI", 10, "bold"),
                        borderwidth=0)
        style.map("Treeview",
                  background=[("selected", COLORS["accent"])],
                  foreground=[("selected", "#ffffff")])

        style.configure("TCheckbutton",
                        background=COLORS["card"],
                        foreground=COLORS["text"],
                        font=("Segoe UI", 10))
        style.configure("TSpinbox",
                        fieldbackground=COLORS["card2"],
                        foreground=COLORS["text"])
        style.configure("TScrollbar",
                        background=COLORS["card2"],
                        troughcolor=COLORS["card"],
                        arrowcolor=COLORS["text"])
        style.configure("TCombobox",
                        fieldbackground=COLORS["card2"],
                        background=COLORS["card2"],
                        foreground=COLORS["text"])

    def build_header(self):
        h = tk.Frame(self.root, bg=COLORS["card"], height=58)
        h.pack(fill="x")
        h.pack_propagate(False)

        left = tk.Frame(h, bg=COLORS["card"])
        left.pack(side="left", padx=20, pady=8)
        tk.Label(left, text="WINDOWS FOCUS RESCUE", font=("Segoe UI", 15, "bold"),
                 bg=COLORS["card"], fg=COLORS["accent"]).pack(anchor="w")
        tk.Label(left, text="Focus • Track • Limit", font=("Segoe UI", 9),
                 bg=COLORS["card"], fg=COLORS["light"]).pack(anchor="w")

        self.header_status = tk.Label(h, text="● ACTIVE", font=("Segoe UI", 10, "bold"),
                                      bg=COLORS["card"], fg=COLORS["success"])
        self.header_status.pack(side="right", padx=20)

    # ---------- PASSWORD (salted PBKDF2) ----------
    def _hash(self, pw: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERATIONS)
        return salt.hex() + ":" + digest.hex()

    def _verify(self, pw: str, stored: str) -> bool:
        try:
            salt_hex, digest_hex = stored.split(":")
            salt = bytes.fromhex(salt_hex)
            check = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERATIONS)
            return secrets.compare_digest(check.hex(), digest_hex)
        except Exception:
            return False

    def load(self):
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE) as f:
                d = json.load(f)
            self.history = d.get("history", {})
            today = str(date.today())
            if today in self.history:
                self.tracker.load(self.history[today])
            self.app_limits = d.get("app_limits", {})
            self.selected = set(d.get("selected", []))
            self.parent_password_hash = d.get("parent_pw")
            self.theme_mode = d.get("theme_mode", "system")
            self.palette_name = d.get("palette_name", "Original")
            if self.palette_name not in PALETTES:
                self.palette_name = "Original"
        except Exception:
            pass

    def save(self):
        today = str(date.today())
        self.history[today] = self.tracker.get_stats()
        cutoff = date.today() - td(days=HISTORY_RETENTION_DAYS)
        self.history = {k: v for k, v in self.history.items() if date.fromisoformat(k) >= cutoff}
        data = {
            "history": self.history,
            "app_limits": self.app_limits,
            "selected": list(self.selected),
            "parent_pw": self.parent_password_hash,
            "theme_mode": self.theme_mode,
            "palette_name": self.palette_name,
        }
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def auto_save(self):
        self.save()
        self.root.after(AUTOSAVE_MS, self.auto_save)

    def on_close(self):
        self.hide_block_overlay()
        self.save()
        self.tracker.stop()
        self.root.destroy()

    def _load_installed(self):
        self.installed = get_installed_apps()
        self.root.after(0, self.refresh_limits)

    def fmt(self, s):
        return str(timedelta(seconds=int(s)))

    def period_total(self, days):
        total = 0.0
        today = date.today()
        for i in range(days):
            d = str(today - td(days=i))
            if d in self.history:
                total += sum(self.history[d].values())
        total = total - sum(self.history.get(str(today), {}).values()) + self.tracker.get_total()
        return total

    def require_parent(self) -> bool:
        if self.is_parent_unlocked:
            return True
        if not self.parent_password_hash:
            messagebox.showinfo("Parent Setup", "No parent password set yet.\nGo to Dashboard → Who is using the PC to create one.")
            return False
        pw = simpledialog.askstring("Parent Authorization", "Enter parent password:", show="*")
        if pw and self._verify(pw, self.parent_password_hash):
            self.is_parent_unlocked = True
            self.status.config(text=" Parent unlocked")
            return True

        # Wrong/cancelled password: simply deny access without another popup.
        return False

    # ---------- DASHBOARD ----------
    def init_dashboard(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="  Dashboard  ")

        card1 = tk.Frame(f, bg=COLORS["card"], padx=20, pady=16)
        card1.pack(fill="x", pady=(0, 12))
        tk.Label(card1, text="CUSTOMIZATION", font=("Segoe UI", 11, "bold"),
                 bg=COLORS["card"], fg=COLORS["accent"]).pack(anchor="w")

        mode_row = tk.Frame(card1, bg=COLORS["card"])
        mode_row.pack(anchor="w", pady=(10, 4), fill="x")
        tk.Label(mode_row, text="Appearance:", width=14, anchor="w",
                 bg=COLORS["card"], fg=COLORS["text_dim"], font=("Segoe UI", 9)).pack(side="left")
        mode_var = tk.StringVar(value=self.MODE_DISPLAY[self.theme_mode])
        mode_box = ttk.Combobox(mode_row, textvariable=mode_var, state="readonly", width=14,
                                 values=list(self.MODE_DISPLAY.values()))
        mode_box.pack(side="left", padx=(6, 0))

        def on_mode_pick(event=None, var=mode_var):
            reverse = {v: k for k, v in self.MODE_DISPLAY.items()}
            self.theme_mode = reverse[var.get()]
            self.on_theme_setting_changed()
        mode_box.bind("<<ComboboxSelected>>", on_mode_pick)

        palette_row = tk.Frame(card1, bg=COLORS["card"])
        palette_row.pack(anchor="w", pady=(4, 4), fill="x")
        tk.Label(palette_row, text="Color palette:", width=14, anchor="w",
                 bg=COLORS["card"], fg=COLORS["text_dim"], font=("Segoe UI", 9)).pack(side="left")
        palette_var = tk.StringVar(value=self.palette_name)
        palette_box = ttk.Combobox(palette_row, textvariable=palette_var, state="readonly", width=22,
                                    values=list(PALETTES.keys()))
        palette_box.pack(side="left", padx=(6, 0))

        def on_palette_pick(event=None, var=palette_var):
            self.palette_name = var.get()
            self.on_theme_setting_changed()
        palette_box.bind("<<ComboboxSelected>>", on_palette_pick)

        note = f"Currently: {self.MODE_DISPLAY[self.theme_mode]}"
        if self.theme_mode == "system":
            note += f"  (resolved to {self.effective_mode().title()})"
        tk.Label(card1, text=note, bg=COLORS["card"], fg=COLORS["sky"],
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))

        card2 = tk.Frame(f, bg=COLORS["card"], padx=20, pady=16)
        card2.pack(fill="x", pady=(0, 12))
        tk.Label(card2, text="WHO IS USING THE PC", font=("Segoe UI", 11, "bold"),
                 bg=COLORS["card"], fg=COLORS["accent"]).pack(anchor="w")
        tk.Label(card2, text="Parents can protect app limits with a password.",
                 bg=COLORS["card"], fg=COLORS["text_dim"], font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 10))

        btn_row = tk.Frame(card2, bg=COLORS["card"])
        btn_row.pack(anchor="w")
        ttk.Button(btn_row, text="Set / Change Parent Password", style="Accent.TButton",
                   command=self.set_parent_pw).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Lock Parent Mode", command=self.lock_parent).pack(side="left")

        card3 = tk.Frame(f, bg=COLORS["card"], padx=20, pady=16)
        card3.pack(fill="x")
        tk.Label(card3, text="QUICK ACTIONS", font=("Segoe UI", 11, "bold"),
                 bg=COLORS["card"], fg=COLORS["accent"]).pack(anchor="w")
        row = tk.Frame(card3, bg=COLORS["card"])
        row.pack(anchor="w", pady=(10, 0))
        ttk.Button(row, text="Reset Today", command=self.reset_today).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Save Now", command=self.manual_save).pack(side="left")

    def set_parent_pw(self):
        # Password setup/change is intentionally allowed without entering
        # the existing password. The new password still has to be entered
        # twice and match before it is saved.
        dialog = tk.Toplevel(self.root)
        dialog.title("Set Parent Password")
        dialog.configure(bg=COLORS["bg"])
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        width, height = 420, 245
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        card = tk.Frame(dialog, bg=COLORS["card"], padx=24, pady=20)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        tk.Label(card, text="SET PARENT PASSWORD", font=("Segoe UI", 12, "bold"),
                 bg=COLORS["card"], fg=COLORS["accent"]).pack(anchor="w")
        tk.Label(card, text="Enter the new password twice to confirm it.",
                 font=("Segoe UI", 9), bg=COLORS["card"],
                 fg=COLORS["text_dim"]).pack(anchor="w", pady=(4, 14))

        fields = tk.Frame(card, bg=COLORS["card"])
        fields.pack(fill="x")

        tk.Label(fields, text="New password:", width=16, anchor="w",
                 bg=COLORS["card"], fg=COLORS["text"]).grid(row=0, column=0, sticky="w", pady=5)
        pw1_entry = ttk.Entry(fields, show="*", width=25)
        pw1_entry.grid(row=0, column=1, sticky="ew", pady=5)

        tk.Label(fields, text="Confirm password:", width=16, anchor="w",
                 bg=COLORS["card"], fg=COLORS["text"]).grid(row=1, column=0, sticky="w", pady=5)
        pw2_entry = ttk.Entry(fields, show="*", width=25)
        pw2_entry.grid(row=1, column=1, sticky="ew", pady=5)
        fields.columnconfigure(1, weight=1)

        error_label = tk.Label(card, text="", font=("Segoe UI", 9),
                               bg=COLORS["card"], fg=COLORS["warning"])
        error_label.pack(anchor="w", pady=(5, 0))

        def save_password():
            pw1 = pw1_entry.get()
            pw2 = pw2_entry.get()
            if not pw1:
                error_label.config(text="Please enter a password.")
                pw1_entry.focus_set()
                return
            if not pw2:
                error_label.config(text="Please confirm the password.")
                pw2_entry.focus_set()
                return
            if pw1 != pw2:
                error_label.config(text="Passwords do not match.")
                pw2_entry.delete(0, tk.END)
                pw2_entry.focus_set()
                return

            self.parent_password_hash = self._hash(pw1)
            self.is_parent_unlocked = True
            self.save()
            dialog.destroy()
            self.status.config(text=" Parent password set")
            messagebox.showinfo("Done", "Parent password set successfully.")

        buttons = tk.Frame(card, bg=COLORS["card"])
        buttons.pack(anchor="e", pady=(8, 0))

        # Use regular Tk buttons here instead of ttk buttons so the text
        # remains visible across Windows themes/palettes.
        cancel_btn = tk.Button(
            buttons,
            text="Cancel",
            command=dialog.destroy,
            bg=COLORS["card2"],
            fg=COLORS["text"],
            activebackground=shade(COLORS["card2"], 1.10),
            activeforeground=COLORS["text"],
            font=("Segoe UI", 10),
            relief="flat",
            bd=0,
            padx=16,
            pady=7,
            cursor="hand2"
        )
        cancel_btn.pack(side="left", padx=(0, 8))

        save_btn = tk.Button(
            buttons,
            text="Save Password",
            command=save_password,
            bg=COLORS["accent"],
            fg="#ffffff",
            activebackground=shade(COLORS["accent"], 0.85),
            activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            bd=0,
            padx=16,
            pady=7,
            cursor="hand2"
        )
        save_btn.pack(side="left")

        dialog.bind("<Return>", lambda e: save_password())
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        pw1_entry.focus_set()

    def lock_parent(self):
        self.is_parent_unlocked = False
        self.status.config(text=" Parent mode locked")

    def reset_today(self):
        if messagebox.askyesno("Reset", "Clear today's data?"):
            self.tracker.reset()
            self.save()
            self.status.config(text=" Today reset")

    def manual_save(self):
        self.save()
        self.status.config(text=" Saved")

    # ---------- APP LIMITS ----------
    def init_limits(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="  App Limits  ")

        top = tk.Frame(f, bg=COLORS["card"], padx=14, pady=10)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="Set a daily minute limit for each app individually",
                 bg=COLORS["card"], fg=COLORS["text_dim"], font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_limits).pack(side="right")

        canvas = tk.Canvas(f, bg=COLORS["card"], highlightthickness=0)
        sb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        self.limits_inner = tk.Frame(canvas, bg=COLORS["card"])
        self.limits_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.limits_inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        sb.pack(side="right", fill="y")

        def wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self.limit_widgets = {}

    def refresh_limits(self):
        if not self.require_parent():
            return

        for w in self.limits_inner.winfo_children():
            w.destroy()
        self.limit_widgets.clear()

        running = dict(self.tracker.get_running())
        combined = dict(running)
        for k, v in self.installed.items():
            if k not in combined:
                combined[k] = v

        hdr = tk.Frame(self.limits_inner, bg=COLORS["card"])
        hdr.pack(fill="x", padx=8, pady=(4, 8))
        tk.Label(hdr, text="App", width=28, anchor="w", bg=COLORS["card"],
                 fg=COLORS["accent"], font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(hdr, text="Limit (min)", width=12, anchor="center", bg=COLORS["card"],
                 fg=COLORS["accent"], font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(hdr, text="Enabled", width=10, anchor="center", bg=COLORS["card"],
                 fg=COLORS["accent"], font=("Segoe UI", 9, "bold")).pack(side="left")

        for clean, name in sorted(combined.items(), key=lambda x: x[1].lower()):
            row = tk.Frame(self.limits_inner, bg=COLORS["card"])
            row.pack(fill="x", padx=8, pady=3)

            prefix = "● " if clean in running else "   "
            tk.Label(row, text=f"{prefix}{name}", width=28, anchor="w",
                     bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10)).pack(side="left")

            var_limit = tk.StringVar(value=str(self.app_limits.get(clean, DEFAULT_APP_LIMIT_MINUTES)))
            spin = ttk.Spinbox(row, from_=0, to=600, width=8, textvariable=var_limit)
            spin.pack(side="left", padx=6)

            var_en = tk.BooleanVar(value=clean in self.selected)

            def toggle(c=clean, v=var_en, lim=var_limit):
                if v.get():
                    self.selected.add(c)
                    try:
                        self.app_limits[c] = int(lim.get())
                    except Exception:
                        self.app_limits[c] = DEFAULT_APP_LIMIT_MINUTES
                else:
                    self.selected.discard(c)
                    self.app_limits.pop(c, None)
                self.save()

            ttk.Checkbutton(row, variable=var_en, command=toggle).pack(side="left", padx=10)

            def save_limit(c=clean, lim=var_limit, en=var_en):
                if en.get():
                    try:
                        self.app_limits[c] = int(lim.get())
                        self.save()
                    except Exception:
                        pass
            spin.bind("<FocusOut>", lambda e, fn=save_limit: fn())
            spin.bind("<Return>", lambda e, fn=save_limit: fn())

            self.limit_widgets[clean] = (var_limit, var_en)

    # ---------- TIMED APP BLOCKER ----------
    def get_foreground_info(self):
        """Return (app_name, hwnd) for the currently focused non-system app."""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None, None

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid or pid == os.getpid():
                return None, hwnd

            app = clean_name(psutil.Process(pid).name())
            if is_system(app):
                return None, hwnd

            return app, hwnd
        except Exception:
            return None, None

    def check_app_limits(self):
        """
        If an enabled app reaches its daily foreground-time limit,
        cover that app with the blocker overlay.
        """
        try:
            # Keep an existing blocker stationary. Do NOT destroy/recreate it
            # just because focus briefly changes; that recreation caused flashing.
            if self.overlay is not None:
                try:
                    if self.overlay.winfo_exists():
                        self.overlay.attributes("-topmost", True)
                        self.overlay.lift()
                        return
                except Exception:
                    self.overlay = None

            if self.overlay is None:
                app, hwnd = self.get_foreground_info()

                if app is not None and app in self.selected:
                    limit = self.app_limits.get(app)

                    if limit is not None:
                        try:
                            limit_seconds = max(0, int(limit)) * 60
                        except (TypeError, ValueError):
                            limit_seconds = None

                        if limit_seconds is not None:
                            used_seconds = self.tracker.get_stats().get(app, 0)
                            effective_limit = limit_seconds + self.extra_time.get(app, 0)

                            if used_seconds >= effective_limit:
                                self.show_block_overlay(
                                    app,
                                    hwnd,
                                    used_seconds,
                                    limit_seconds
                                )

        except Exception as e:
            print("Limit checker:", e)

        # Check frequently so the overlay appears close to the exact limit.
        self.root.after(POLL_INTERVAL_MS, self.check_app_limits)

    def show_block_overlay(self, app_name, target_hwnd, used_seconds, limit_seconds):
        """Display an overlay over the app whose daily limit was reached."""
        if self.overlay is not None:
            return

        try:
            left, top, right, bottom = win32gui.GetWindowRect(target_hwnd)
            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                raise ValueError("Invalid target window dimensions")
        except Exception:
            left = 0
            top = 0
            width = self.root.winfo_screenwidth()
            height = self.root.winfo_screenheight()

        self.overlay_target_hwnd = target_hwnd
        self.overlay_target_app = app_name

        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.geometry(f"{width}x{height}+{left}+{top}")
        self.overlay.attributes("-topmost", True)
        self.overlay.configure(bg=COLORS["bg"])
        self.overlay.protocol("WM_DELETE_WINDOW", lambda: None)

        content = tk.Frame(self.overlay, bg=COLORS["bg"])
        content.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            content,
            text="LIMIT REACHED",
            font=("Segoe UI", 13, "bold"),
            fg=COLORS["warning"],
            bg=COLORS["bg"]
        ).pack(pady=(0, 15))

        tk.Label(
            content,
            text=f"{friendly_name(app_name)} is blocked",
            font=("Segoe UI", 28, "bold"),
            fg=COLORS["text"],
            bg=COLORS["bg"]
        ).pack()

        limit_minutes = int(limit_seconds / 60)
        minute_word = "minute" if limit_minutes == 1 else "minutes"

        tk.Label(
            content,
            text=f"You've reached your {limit_minutes} {minute_word} daily limit.",
            font=("Segoe UI", 12),
            fg=COLORS["text_dim"],
            bg=COLORS["bg"]
        ).pack(pady=(12, 4))

        button_row = tk.Frame(content, bg=COLORS["bg"])
        button_row.pack(pady=(20, 10))

        ttk.Button(
            button_row,
            text="+5 More Minutes",
            style="Accent.TButton",
            command=lambda app=app_name: self.add_more_time(app, 5)
        ).pack(side="left", padx=6)

        ttk.Button(
            button_row,
            text="Close App",
            command=lambda app=app_name: self.close_blocked_app(app)
        ).pack(side="left", padx=6)

        tk.Label(
            content,
            text="Switch to another app to continue.",
            font=("Segoe UI", 10),
            fg=COLORS["text_dim"],
            bg=COLORS["bg"]
        ).pack(pady=(4, 0))

        self.overlay.lift()

    def add_more_time(self, app_name, minutes=5):
        """Grant temporary extra time without changing the saved daily limit."""
        # Use the app's existing parent authorization system.
        if not self.require_parent():
            return

        app_name = clean_name(app_name)
        self.extra_time[app_name] = self.extra_time.get(app_name, 0) + (minutes * 60)

        self.hide_block_overlay()

        try:
            self.status.config(
                text=f" Added {minutes} more minutes to {friendly_name(app_name)}"
            )
        except Exception:
            pass

    def close_blocked_app(self, app_name):
        """Close the blocked application's processes and remove the overlay."""
        app_name = clean_name(app_name)

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = proc.info.get("name")
                if name and clean_name(name) == app_name:
                    proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        self.hide_block_overlay()

        try:
            self.status.config(text=f" Closed {friendly_name(app_name)}")
        except Exception:
            pass

    def hide_block_overlay(self):
        if self.overlay is not None:
            try:
                self.overlay.destroy()
            except Exception:
                pass

        self.overlay = None
        self.overlay_target_hwnd = None
        self.overlay_target_app = None

    # ---------- TRACKING ----------
    def init_tracking(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="  Tracking  ")

        body = tk.Frame(f, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=COLORS["card"])
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Label(left, text="  FOREGROUND TIME", font=("Segoe UI", 10, "bold"),
                 bg=COLORS["card"], fg=COLORS["accent"]).pack(anchor="w", padx=10, pady=(12, 6))
        self.tree = ttk.Treeview(left, columns=("app", "time"), show="headings", height=18)
        self.tree.heading("app", text="Application")
        self.tree.heading("time", text="Time")
        self.tree.column("app", width=280)
        self.tree.column("time", width=100, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        right = tk.Frame(body, bg=COLORS["card"])
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="  CURRENTLY RUNNING", font=("Segoe UI", 10, "bold"),
                 bg=COLORS["card"], fg=COLORS["accent"]).pack(anchor="w", padx=10, pady=(12, 6))
        self.run_list = tk.Listbox(right, bg=COLORS["card"], fg=COLORS["text"],
                                   selectbackground=COLORS["accent"], selectforeground="#ffffff",
                                   font=("Segoe UI", 10), borderwidth=0, highlightthickness=0,
                                   activestyle="none")
        self.run_list.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self.run_list.bind("<MouseWheel>", lambda e: self.run_list.yview_scroll(int(-1*(e.delta/120)), "units"))

    # ---------- STATISTICS ----------
    def init_statistics(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="  Statistics  ")

        cards = tk.Frame(f, bg=COLORS["bg"])
        cards.pack(fill="x", pady=(0, 12))
        self.stat_cards = {}
        for key, title in [("today", "TODAY"), ("week", "THIS WEEK"), ("month", "THIS MONTH")]:
            c = tk.Frame(cards, bg=COLORS["card"], padx=16, pady=12)
            c.pack(side="left", fill="both", expand=True, padx=(0, 8))
            tk.Label(c, text=title, font=("Segoe UI", 9, "bold"),
                     bg=COLORS["card"], fg=COLORS["text_dim"]).pack(anchor="w")
            lbl = tk.Label(c, text="0:00:00", font=("Segoe UI", 16, "bold"),
                           bg=COLORS["card"], fg=COLORS["accent"])
            lbl.pack(anchor="w", pady=(4, 0))
            self.stat_cards[key] = lbl

        tk.Label(f, text="  INDIVIDUAL APP STATS (Today)", font=("Segoe UI", 10, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"]).pack(anchor="w", pady=(4, 6))

        self.stats_tree = ttk.Treeview(f, columns=("app", "time", "limit", "status"), show="headings", height=16)
        self.stats_tree.heading("app", text="Application")
        self.stats_tree.heading("time", text="Time Today")
        self.stats_tree.heading("limit", text="Limit")
        self.stats_tree.heading("status", text="Status")
        self.stats_tree.column("app", width=260)
        self.stats_tree.column("time", width=110, anchor="center")
        self.stats_tree.column("limit", width=90, anchor="center")
        self.stats_tree.column("status", width=110, anchor="center")
        self.stats_tree.pack(fill="both", expand=True, padx=4)

    def update_ui(self):
        try:
            stats = self.tracker.get_stats()
            current = self.tracker.current_app

            for i in self.tree.get_children():
                self.tree.delete(i)
            for clean, sec in sorted(stats.items(), key=lambda x: x[1], reverse=True):
                if sec >= 1:
                    self.tree.insert("", "end", values=(friendly_name(clean), self.fmt(sec)))

            self.run_list.delete(0, tk.END)
            for clean, name in self.tracker.get_running():
                prefix = "● " if clean == current else "   "
                self.run_list.insert(tk.END, f"{prefix}{name}")

            self.stat_cards["today"].config(text=self.fmt(self.tracker.get_total()))
            self.stat_cards["week"].config(text=self.fmt(self.period_total(7)))
            self.stat_cards["month"].config(text=self.fmt(self.period_total(30)))

            for i in self.stats_tree.get_children():
                self.stats_tree.delete(i)
            for clean, sec in sorted(stats.items(), key=lambda x: x[1], reverse=True):
                if sec < 1:
                    continue
                limit = self.app_limits.get(clean)
                limit_str = f"{limit} min" if limit else "—"
                status = "OVER LIMIT" if (limit is not None and sec >= limit * 60) else "OK"
                self.stats_tree.insert("", "end", values=(friendly_name(clean), self.fmt(sec), limit_str, status))

            over = any(sec >= self.app_limits.get(c, 9999) * 60 for c, sec in stats.items() if c in self.app_limits)
            if over:
                self.header_status.config(text="● LIMIT HIT", fg=COLORS["warning"])
            else:
                self.header_status.config(text="● ACTIVE", fg=COLORS["success"])

        except Exception as e:
            print("UI:", e)
        self.root.after(UI_REFRESH_MS, self.update_ui)
