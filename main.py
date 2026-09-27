"""Entry point. Run with: python main.py"""

import tkinter as tk
from app import ScreenTimeApp


def main():
    root = tk.Tk()
    ScreenTimeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
