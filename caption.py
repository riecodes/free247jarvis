"""A short caption above other windows, for when the user may not hear the voice. voice.mjs starts one per caption:
pythonw caption.py <text> [seconds]

It takes no focus and no clicks, and stays out of screen shares and recordings, so a call never sees it (set
CAPTION_VISIBLE=1 in .env to show it there too)."""
import ctypes
import os
import sys
import tkinter as tk

GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED = 0x8, 0x20, 0x80, 0x80000
WS_EX_NOACTIVATE = 0x8000000
WDA_EXCLUDEFROMCAPTURE = 0x11


def main(text: str, seconds: float) -> None:
    user32 = ctypes.windll.user32
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # or it blurs on a scaled screen
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True, "-alpha", 0.94)
    root.configure(bg="#10161c")
    wrap = root.winfo_screenwidth() * 6 // 10
    tk.Label(root, text=text, font=("Segoe UI", 18), fg="#ffffff", bg="#10161c", wraplength=wrap, justify="center",
             padx=28, pady=18).pack()
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2
    y = root.winfo_screenheight() - root.winfo_reqheight() - root.winfo_screenheight() // 10  # above the taskbar
    root.geometry(f"+{x}+{y}")
    window = user32.GetParent(root.winfo_id())
    user32.SetWindowLongW(window, GWL_EXSTYLE, user32.GetWindowLongW(window, GWL_EXSTYLE) | WS_EX_TOPMOST
                          | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE)
    if os.environ.get("CAPTION_VISIBLE") != "1":
        user32.SetWindowDisplayAffinity(window, WDA_EXCLUDEFROMCAPTURE)
    root.deiconify()
    root.after(int(seconds * 1000), root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 10)
