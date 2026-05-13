#!/usr/bin/env python3
# raspdeck_tray.py - system tray for the RaspDeck daemon
# dependencies: pystray, pillow, pyserial

import glob
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

import serial
import pystray
from PIL import Image, ImageDraw

RP2040_VID = "2e8a"
RP2040_PID = "0005"


def find_port():
    for tty in glob.glob("/sys/class/tty/ttyACM*"):
        uevent = Path(tty) / "device" / "uevent"
        if uevent.exists():
            text = uevent.read_text().lower()
            if RP2040_VID in text and RP2040_PID in text:
                return "/dev/" + Path(tty).name
    acm = sorted(glob.glob("/dev/ttyACM*"))
    return acm[0] if acm else None


ICON_PATH = Path.home() / ".local" / "raspdeck" / "tray.png"


def make_icon_image(connected: bool) -> Image.Image:
    if ICON_PATH.exists():
        img = Image.open(ICON_PATH).convert("RGBA")
        if not connected:
            # desaturate when not connected
            r, g, b, a = img.split()
            gray = img.convert("L")
            return Image.merge("RGBA", (gray, gray, gray, a))
        return img

    # fallback
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (80, 200, 120) if connected else (180, 180, 180)
    draw.rounded_rectangle([4, 4, 60, 60], radius=10, fill=color)
    dot = (20, 20, 20)
    for row in range(3):
        for col in range(3):
            x = 18 + col * 14
            y = 18 + row * 14
            draw.ellipse([x, y, x+6, y+6], fill=dot)
    return img


class RaspDeckTray:
    def __init__(self):
        self._ser      = None
        self._port     = None
        self._lock     = threading.Lock()
        self._icon     = None

        self._port = find_port()
        if self._port:
            try:
                self._ser = serial.Serial(self._port, 115200, timeout=1)
            except serial.SerialException:
                self._ser  = None
                self._port = None

        tooltip = f"RaspDeck ({self._port})" if self._port else "RaspDeck (not connected)"
        connected = self._ser is not None

        menu = pystray.Menu(
            pystray.MenuItem("Send command...", self._open_send_window),
            pystray.MenuItem("Reconnect",       self._reconnect),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",            self._quit),
        )

        self._icon = pystray.Icon(
            "raspdeck",
            make_icon_image(connected),
            tooltip,
            menu,
        )

    def _send(self, command: str):
        with self._lock:
            if self._ser and self._ser.is_open:
                try:
                    self._ser.write((command.strip() + "\n").encode())
                    return True
                except serial.SerialException:
                    self._ser  = None
                    self._port = None
                    self._update_icon(connected=False)
        return False

    def _update_icon(self, connected: bool):
        tooltip = f"RaspDeck ({self._port})" if self._port else "RaspDeck (not connected)"
        self._icon.icon  = make_icon_image(connected)
        self._icon.title = tooltip

    def _reconnect(self, icon=None, item=None):
        with self._lock:
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
            self._port = find_port()
            if self._port:
                try:
                    self._ser = serial.Serial(self._port, 115200, timeout=1)
                except serial.SerialException:
                    self._ser  = None
                    self._port = None
            else:
                self._ser = None
        self._update_icon(connected=self._ser is not None)

    def _open_send_window(self, icon=None, item=None):
        def _build():
            win = tk.Tk()
            win.title("RaspDeck — Send command")
            win.resizable(False, False)
            win.attributes("-topmost", True)

            tk.Label(win, text="Command:", padx=10, pady=6).grid(row=0, column=0, sticky="e")
            entry = tk.Entry(win, width=32)
            entry.grid(row=0, column=1, padx=(0, 10), pady=10)
            entry.focus()

            status = tk.Label(win, text="", fg="gray", padx=10)
            status.grid(row=1, column=0, columnspan=2, pady=(0, 4))

            def send(_event=None):
                cmd = entry.get().strip()
                if not cmd:
                    return
                ok = self._send(cmd)
                if ok:
                    status.config(text=f"Sent: {cmd}", fg="green")
                    entry.delete(0, tk.END)
                else:
                    status.config(text="Not connected", fg="red")

            btn = tk.Button(win, text="Send", command=send, width=8)
            btn.grid(row=0, column=2, padx=(0, 10))
            win.bind("<Return>", send)

            win.mainloop()

        # tkinter runs on its own thread
        threading.Thread(target=_build, daemon=True).start()

    def _quit(self, icon=None, item=None):
        with self._lock:
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
        self._icon.stop()

    def run(self):
        self._icon.run()


if __name__ == "__main__":
    RaspDeckTray().run()
