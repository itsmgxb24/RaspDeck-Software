import sys
import os
import platform
import tkinter as tk
import serial
import serial.tools.list_ports
import threading
import time

URL         = "https://itsmgxb.online/raspdeck/systemd-dependency"
OS          = platform.system()
PORT        = "/dev/ttyACM0" if OS != "Windows" else "COM1"
BASE_URL    = "https://raw.githubusercontent.com/itsmgxb24/RaspDeck-Software/main/"
INSTALL_DIR = os.path.expanduser("~/.local/raspdeck")


def get_serial(port=PORT):
    ser = serial.Serial(port=port, baudrate=115200, timeout=1)
    time.sleep(2)
    return ser


def find_serial_ports():
    import glob
    if OS == "Windows":
        ports = []
        for i in range(1, 257):
            port = f"COM{i}"
            try:
                s = serial.Serial(port)
                s.close()
                ports.append(port)
            except (serial.SerialException, OSError):
                pass
        return ports
    return (
        glob.glob("/dev/ttyACM*")
        + glob.glob("/dev/ttyUSB*")
        + glob.glob("/dev/ttyS*")
    )


def _download(url: str, dest: str):
    import subprocess, urllib.request
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if OS == "Linux":
        subprocess.run(["wget", "-q", "-O", dest, url], check=True)
    else:
        urllib.request.urlretrieve(url, dest)
    print(f"  Downloaded -> {dest}")


def _check_deps(deps: list):
    import importlib
    missing = []
    for pkg, import_name in deps:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("  Missing Python packages:")
        for pkg in missing:
            print(f"    pip install {pkg} --break-system-packages")
    else:
        print("  All Python dependencies satisfied.")


def _ensure_on_path_linux():
    bashrc = os.path.expanduser("~/.bashrc")
    export = f'export PATH="$PATH:{INSTALL_DIR}"'
    try:
        content = open(bashrc).read()
    except FileNotFoundError:
        content = ""
    if INSTALL_DIR not in content:
        with open(bashrc, "a") as f:
            f.write(f"\n{export}\n")
        print(f"  Added {INSTALL_DIR} to PATH in ~/.bashrc")
        print("  Run: source ~/.bashrc")
    else:
        print(f"  {INSTALL_DIR} already in PATH.")


def install_tool():
    print("Installing rd-tool...")
    os.makedirs(INSTALL_DIR, exist_ok=True)
    dest = os.path.join(INSTALL_DIR, "rd-tool.py")
    _download(f"{BASE_URL}tool/rd-tool.py", dest)
    if OS == "Linux":
        os.chmod(dest, 0o755)
        wrapper = os.path.join(INSTALL_DIR, "rd-tool")
        with open(wrapper, "w") as f:
            f.write(f"#!/bin/sh\nexec python3 {dest} \"$@\"\n")
        os.chmod(wrapper, 0o755)
        print(f"  Wrapper created: {wrapper}")
        _ensure_on_path_linux()
    _check_deps([("pyserial", "serial"), ("pynput", "pynput")])
    print("rd-tool installed.")


def install_daemon_linux():
    import subprocess
    print("Installing RaspDeck daemon...")
    os.makedirs(INSTALL_DIR, exist_ok=True)
    systemd_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(systemd_dir, exist_ok=True)
    _download(
        f"{BASE_URL}daemon/raspdeck_linux_daemon_v1_2.py",
        os.path.join(INSTALL_DIR, "raspdeck_linux_daemon_v1_2.py"),
    )
    _download(
        f"{BASE_URL}daemon/raspdeck-daemon.service",
        os.path.join(systemd_dir, "raspdeck-daemon.service"),
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "enable", "raspdeck-daemon.service"])
    subprocess.run(["systemctl", "--user", "start",  "raspdeck-daemon.service"])
    _check_deps([("pyserial", "serial"), ("pynput", "pynput")])
    print("Daemon installed and started.")


def install_daemon_windows():
    import subprocess
    print("Installing RaspDeck daemon (Windows)...")
    os.makedirs(INSTALL_DIR, exist_ok=True)
    daemon_path = os.path.join(INSTALL_DIR, "raspdeck_linux_daemon_v1_2.py")
    _download(f"{BASE_URL}daemon/raspdeck_linux_daemon_v1_2.py", daemon_path)
    task_name = "RaspDeckDaemon"
    result = subprocess.run([
        "schtasks", "/create", "/tn", task_name,
        "/tr", f'"{sys.executable}" "{daemon_path}"',
        "/sc", "onlogon", "/rl", "highest", "/f",
    ], capture_output=True, text=True)
    if result.returncode == 0:
        subprocess.run(["schtasks", "/run", "/tn", task_name])
        print(f"Task '{task_name}' registered and started.")
    else:
        print("Failed to register scheduled task:")
        print(result.stderr)
    _check_deps([("pyserial", "serial"), ("pynput", "pynput")])
    print("Daemon installed.")


def install_daemon():
    if OS == "Linux":
        install_daemon_linux()
    elif OS == "Windows":
        install_daemon_windows()
    else:
        print(f"Unsupported OS: {OS}.")


def install_tray_linux():
    import subprocess
    print("Installing RaspDeck tray...")
    os.makedirs(INSTALL_DIR, exist_ok=True)
    systemd_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(systemd_dir, exist_ok=True)
    _download(
        f"{BASE_URL}tray/rd-tray.py",
        os.path.join(INSTALL_DIR, "rd-tray.py"),
    )
    _download(
        f"{BASE_URL}tray/rd-tray.service",
        os.path.join(systemd_dir, "rd-tray.service"),
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "enable", "rd-tray.service"])
    subprocess.run(["systemctl", "--user", "start",  "rd-tray.service"])
    _check_deps([("pyserial", "serial"), ("pystray", "pystray"), ("pillow", "PIL")])
    print("Tray installed and started.")
    print(f"  Place your icon at: {INSTALL_DIR}/tray.png")


def install_tray_windows():
    import subprocess
    print("Installing RaspDeck tray (Windows)...")
    os.makedirs(INSTALL_DIR, exist_ok=True)
    tray_path = os.path.join(INSTALL_DIR, "rd-tray.py")
    _download(f"{BASE_URL}tray/rd-tray.py", tray_path)
    task_name = "RaspDeckTray"
    result = subprocess.run([
        "schtasks", "/create", "/tn", task_name,
        "/tr", f'"{sys.executable}" "{tray_path}"',
        "/sc", "onlogon", "/rl", "limited", "/f",
    ], capture_output=True, text=True)
    if result.returncode == 0:
        subprocess.run(["schtasks", "/run", "/tn", task_name])
        print(f"Task '{task_name}' registered and started.")
    else:
        print("Failed to register scheduled task:")
        print(result.stderr)
    _check_deps([("pyserial", "serial"), ("pystray", "pystray"), ("pillow", "PIL")])
    print("Tray installed.")


def install_tray():
    if OS == "Linux":
        install_tray_linux()
    elif OS == "Windows":
        install_tray_windows()
    else:
        print(f"Unsupported OS: {OS}.")


def install_all():
    print("Installing RaspDeck (tool + daemon + tray)...")
    install_tool()
    install_daemon()
    install_tray()
    print("Done.")


def update():
    print("Updating RaspDeck...")
    updated = False

    # dest path -> repo url, only updates files that are already installed
    all_files = {
        os.path.join(INSTALL_DIR, "rd-tool.py"):
            f"{BASE_URL}tool/rd-tool.py",
        os.path.join(INSTALL_DIR, "raspdeck_linux_daemon_v1_2.py"):
            f"{BASE_URL}daemon/raspdeck_linux_daemon_v1_2.py",
        os.path.join(INSTALL_DIR, "rd-tray.py"):
            f"{BASE_URL}tray/rd-tray.py",
        os.path.expanduser("~/.config/systemd/user/raspdeck-daemon.service"):
            f"{BASE_URL}daemon/raspdeck-daemon.service",
        os.path.expanduser("~/.config/systemd/user/rd-tray.service"):
            f"{BASE_URL}tray/rd-tray.service",
    }

    for dest, url in all_files.items():
        if os.path.exists(dest):
            print(f"Updating {os.path.basename(dest)}...")
            try:
                _download(url, dest)
                updated = True
            except Exception as e:
                print(f"  Failed: {e}")
        else:
            print(f"  Skipping {os.path.basename(dest)} (not installed)")

    if updated and OS == "Linux":
        import subprocess
        subprocess.run(["systemctl", "--user", "daemon-reload"])
        for service in ["raspdeck-daemon.service", "rd-tray.service"]:
            unit_path = os.path.expanduser(f"~/.config/systemd/user/{service}")
            if os.path.exists(unit_path):
                subprocess.run(["systemctl", "--user", "restart", service])
                print(f"  Restarted {service}")

    print("Update complete." if updated else "Nothing to update.")


def rasphelp():
    print("Synopsis: rd-tool.py [option]...")
    print("Options:")
    print("  -h, --help                  View this menu.")
    print("  -g, --graphical-interface   Launch the graphical interface.")
    print("  -t, --test-connection       Test the connection to your RaspDeck.")
    print("  -a, --auto-detect           Auto-detect the RaspDeck device port.")
    print("  -i, --install               Install everything (tool + daemon + tray).")
    print("  -d, --install-daemon        Install the RaspDeck daemon only.")
    print("  -r, --install-tray          Install the RaspDeck tray only.")
    print("  -u, --update                Update all installed files from the repo.")
    print("  -s, --setup                 Setup your RaspDeck device.")
    print("  -m, --matrixify             Generate a matrix display lightup.")


def gui():
    print("Graphical interface not supported yet. Use the CLI.")


def auto_detect():
    candidates = find_serial_ports()
    if not candidates:
        print("No serial ports found on this system.")
        return None
    print(f"Scanning {len(candidates)} port(s): {', '.join(candidates)}")
    for port in candidates:
        print(f"  Trying {port} ... ", end="", flush=True)
        try:
            ser = serial.Serial(port=port, baudrate=115200, timeout=2)
            time.sleep(2)
            ser.reset_input_buffer()
            ser.write(b"ping\n")
            response = ser.readline().decode(errors="replace").strip()
            ser.close()
            if response.lower() == "pong":
                print("RaspDeck found!")
                return port
            else:
                print(f"no response (got: {repr(response)})")
        except (serial.SerialException, OSError) as e:
            print(f"skipped ({e})")
    print("RaspDeck not found on any port.")
    return None


def matrixify():
    BAUDRATE = 115200
    chosenPixel  = ""
    chosenPixels = ""
    selected = set()
    ser = None

    root = tk.Tk()
    root.title("matrixify")

    top_frame = tk.Frame(root)
    top_frame.pack(fill="x", padx=5, pady=(5, 0))
    serial_label = tk.Label(
        top_frame, text="pyserial:[searching...]",
        bg="#cccccc", anchor="w", font=("Arial", 11), padx=8, pady=6,
    )
    serial_label.pack(fill="x")

    canvas = tk.Canvas(
        root, width=8*45+2*5, height=8*45+2*5,
        bg="white", highlightthickness=0,
    )
    canvas.pack()

    bottom_frame = tk.Frame(root)
    bottom_frame.pack(fill="x", padx=5, pady=(0, 5))
    info_label = tk.Label(
        bottom_frame, text="", bg="#dddddd",
        anchor="w", font=("Arial", 11), padx=8, pady=6,
    )
    info_label.pack(side="left", fill="x", expand=True)

    def detect_serial():
        nonlocal ser
        ports = serial.tools.list_ports.comports()
        if not ports:
            serial_label.config(text="pyserial:[no ports]")
            return
        for port in ports:
            try:
                serial_label.config(text=f"pyserial:[{port.device}] ping...")
                root.update()
                test_ser = serial.Serial(port.device, BAUDRATE, timeout=1)
                time.sleep(2)
                test_ser.reset_input_buffer()
                start = time.time()
                test_ser.write(b"ping\n")
                response = test_ser.readline().decode().strip()
                elapsed = int((time.time() - start) * 1000)
                if response.lower() == "pong":
                    ser = test_ser
                    serial_label.config(text=f"pyserial:[{port.device}] pong! ({elapsed} ms)")
                    return
                test_ser.close()
            except Exception:
                pass
        serial_label.config(text="pyserial:[no device]")

    def send_to_device():
        nonlocal ser
        if ser is None:
            info_label.config(text="No connection.")
            return
        try:
            data = f"pixels -h {chosenPixels}\n"
            ser.write(data.encode())
            info_label.config(text=f"Sent: {data.strip()}")
        except Exception as e:
            info_label.config(text=f"Send error: {e}")

    def copy_to_clipboard():
        text = info_label.cget("text")
        if text:
            root.clipboard_clear()
            root.clipboard_append(text)

    def update_text():
        nonlocal chosenPixel, chosenPixels
        selected_sorted = sorted(selected)
        chosenPixels = ",".join(str(n) for n in selected_sorted)
        chosenPixel  = f"{selected_sorted[0]},1" if len(selected_sorted) == 1 else ""
        info_label.config(text=chosenPixels if selected_sorted else "")

    def toggle_all():
        if len(selected) == 64:
            for n in list(selected):
                selected.remove(n)
                canvas.itemconfig(rectangles[n], fill="white")
        else:
            for n in range(64):
                if n not in selected:
                    selected.add(n)
                    canvas.itemconfig(rectangles[n], fill="red")
        update_text()

    tk.Button(bottom_frame, text="All On/Off",     command=toggle_all).pack(side="left", padx=(5, 0))
    tk.Button(bottom_frame, text="Send To Device", command=send_to_device).pack(side="left", padx=(5, 0))
    tk.Button(bottom_frame, text="Copy",           command=copy_to_clipboard).pack(side="left", padx=(5, 0))

    rectangles = {}
    for row in range(8):
        for col in range(8):
            number  = row * 8 + col
            x1      = 5 + col * 45
            y1      = 5 + row * 45
            x2, y2  = x1 + 45, y1 + 45
            rect_id = canvas.create_rectangle(x1, y1, x2, y2, fill="white", outline="black")
            canvas.create_text(x1+22, y1+22, text=str(number), font=("Arial", 10))
            rectangles[number] = rect_id

    def left_click(event):
        col = (event.x - 5) // 45
        row = (event.y - 5) // 45
        if 0 <= row < 8 and 0 <= col < 8:
            n = row * 8 + col
            if n not in selected:
                selected.add(n)
                canvas.itemconfig(rectangles[n], fill="red")
                update_text()

    def right_click(event):
        col = (event.x - 5) // 45
        row = (event.y - 5) // 45
        if 0 <= row < 8 and 0 <= col < 8:
            n = row * 8 + col
            if n in selected:
                selected.remove(n)
                canvas.itemconfig(rectangles[n], fill="white")
                update_text()

    canvas.bind("<Button-1>", left_click)
    canvas.bind("<Button-3>", right_click)
    threading.Thread(target=detect_serial, daemon=True).start()
    root.mainloop()


if len(sys.argv) < 2:
    rasphelp()
    sys.exit()

arg = sys.argv[1]

if arg in ("-h", "--help"):
    rasphelp()

elif arg in ("-a", "--auto-detect"):
    port = auto_detect()
    if port:
        print(f"RaspDeck detected on: {port}")
    else:
        sys.exit(1)

elif arg in ("-t", "--test-connection"):
    ser = get_serial()
    print("Connection OK")
    ser.close()

elif arg in ("-i", "--install"):
    print("This will install the RaspDeck tool, daemon, and tray to ~/.local/raspdeck/")
    if input("Continue? y/n: ").strip().lower() == "y":
        install_all()
    else:
        print("Aborted.")

elif arg in ("-d", "--install-daemon"):
    if OS == "Linux":
        print(f"This will install the RaspDeck daemon. Requires systemd. More info: {URL}")
    if input("Continue? y/n: ").strip().lower() == "y":
        install_daemon()
    else:
        print("Aborted.")

elif arg in ("-r", "--install-tray"):
    if input("Install RaspDeck tray? y/n: ").strip().lower() == "y":
        install_tray()
    else:
        print("Aborted.")

elif arg in ("-u", "--update"):
    if input("Pull latest files from repo and restart services? y/n: ").strip().lower() == "y":
        update()
    else:
        print("Aborted.")

elif arg in ("-g", "--graphical-interface"):
    gui()

elif arg in ("-s", "--setup"):
    print("This option is not implemented yet.")

elif arg in ("-m", "--matrixify"):
    matrixify()

else:
    print(f"Unknown option: {arg}")
    rasphelp()
