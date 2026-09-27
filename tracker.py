"""
Background foreground-app time tracker.
Runs its own daemon thread, polling the foreground window once a second
and accumulating time per clean app name. No UI or file I/O here — the
app layer owns persistence.
"""

import time
import threading
from collections import defaultdict

import psutil
import win32gui
import win32process
import win32api

from process_utils import clean_name, is_system, has_visible_window, friendly_name


class AppTimeTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.time_spent = defaultdict(float)
        self.current_app = None
        self._last = time.time()
        self._running = False
        self.is_idle = False

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def get_stats(self):
        with self._lock:
            self._flush()
            return dict(self.time_spent)

    def get_total(self):
        return sum(self.get_stats().values())

    def get_running(self):
        apps = {}
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if p.info["name"] and not is_system(p.info["name"]) and has_visible_window(p.info["pid"]):
                    c = clean_name(p.info["name"])
                    apps[c] = friendly_name(c)
            except Exception:
                continue
        return sorted(apps.items(), key=lambda x: x[1].lower())

    def reset(self):
        with self._lock:
            self.time_spent.clear()
            self.current_app = None
            self._last = time.time()

    def load(self, data):
        with self._lock:
            self.time_spent = defaultdict(float, {k: float(v) for k, v in data.items()})

    def _loop(self):
        while self._running:
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(1.0)

    def _tick(self):
        try:
            idle = (win32api.GetTickCount() - win32api.GetLastInputInfo()) / 1000
            self.is_idle = idle > 50
        except Exception:
            self.is_idle = False

        app = None if self.is_idle else self._foreground()
        now = time.time()
        with self._lock:
            if self.current_app and not self.is_idle:
                self.time_spent[self.current_app] += max(0, now - self._last)
            self.current_app = app
            self._last = now

    def _flush(self):
        if self.current_app and not self.is_idle:
            now = time.time()
            self.time_spent[self.current_app] += max(0, now - self._last)
            self._last = now

    def _foreground(self):
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd or not win32gui.IsWindowVisible(hwnd):
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            name = clean_name(psutil.Process(pid).name())
            return None if is_system(name) else name
        except Exception:
            return None
