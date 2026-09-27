"""
Process discovery and naming helpers.
Everything here talks to Windows via psutil/pywin32 and has no UI or
state of its own — pure lookups and classification.
"""

import winreg

import psutil
import win32gui
import win32process

FRIENDLY_NAMES = {
    "chrome": "Google Chrome", "msedge": "Microsoft Edge", "opera": "Opera",
    "opera_gx": "Opera GX", "firefox": "Firefox", "brave": "Brave",
    "discord": "Discord", "spotify": "Spotify", "steam": "Steam",
    "code": "VS Code", "cursor": "Cursor", "devenv": "Visual Studio",
    "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint",
    "outlook": "Outlook", "teams": "Teams", "slack": "Slack",
    "zoom": "Zoom", "telegram": "Telegram", "whatsapp": "WhatsApp",
    "obs64": "OBS Studio", "vlc": "VLC", "photoshop": "Photoshop",
    "githubdesktop": "GitHub Desktop", "onenote": "OneNote",
    "windowsterminal": "Windows Terminal", "notepad++": "Notepad++",
}

SYSTEM_PROCESSES = {
    "system", "registry", "smss", "csrss", "wininit", "services", "lsass",
    "svchost", "fontdrvhost", "dwm", "winlogon", "runtimebroker",
    "searchhost", "shellexperiencehost", "startmenuexperiencehost",
    "textinputhost", "applicationframehost", "systemsettings", "taskhostw",
    "sihost", "ctfmon", "conhost", "dllhost", "msiexec", "python", "pythonw",
    "explorer", "searchapp", "gamebar", "microsoftedgeupdate", "edgeupdate",
    "steamwebhelper", "discordupdater", "update", "squirrel",
}


def clean_name(n: str) -> str:
    return n.lower().replace(".exe", "").strip()


def friendly_name(n: str) -> str:
    n = clean_name(n)
    return FRIENDLY_NAMES.get(n, n.replace("-", " ").replace("_", " ").title())


def is_system(n: str) -> bool:
    n = clean_name(n)
    return n in SYSTEM_PROCESSES or n.startswith(("windows", "microsoftedge", "msedgewebview", "runtime"))


def has_visible_window(pid: int) -> bool:
    def cb(hwnd, lst):
        if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            _, p = win32process.GetWindowThreadProcessId(hwnd)
            if p == pid and win32gui.GetWindowText(hwnd).strip():
                lst.append(hwnd)
        return True
    lst = []
    try:
        win32gui.EnumWindows(cb, lst)
    except Exception:
        return False
    return bool(lst)


def get_installed_apps():
    apps = {}
    paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for root, path in paths:
        try:
            key = winreg.OpenKey(root, path)
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    try:
                        name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        if name and not any(x in name for x in ["Update", "Runtime", "Redistributable", "Visual C++"]):
                            apps[clean_name(name)] = name.strip()
                    except Exception:
                        pass
                    finally:
                        winreg.CloseKey(sub)
                except Exception:
                    continue
            winreg.CloseKey(key)
        except Exception:
            continue
    return apps
