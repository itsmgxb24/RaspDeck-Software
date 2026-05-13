#!/usr/bin/env python3

import sys
import time
import threading
import queue
import subprocess
import glob
import serial
from pathlib import Path
from pynput.keyboard import Controller, Key

CONFIG_DIR  = Path.home() / ".local" / "raspdeck"
CONFIG_FILE = CONFIG_DIR / "config.conf"

DEFAULT_CONFIG = """\
# RaspDeck config — Linux
# Full documentation: raspdeck_daemon_datasheet.pdf

BRIGHT = 8
# PORT = /dev/ttyACM0

# TRIGGERS
#     <NAME> = onTrigger
#     <NAME> = 500
#     VOLUME = 200
#
# ACTIONS
#     <EVENT> = <action>
#     if <condition> then:
#         <action>
#
#   Events:     BTN:<id>:P/R   ENC:+1   ENC:-1   ENCBTN:P/R
#   Actions:    exec=<cmd>   print=<text>   log=<text>
#               volume_up(<step>)   volume_down(<step>)   volume_mute
#               media_play_pause   media_next   media_prev   media_stop
#               trigger <NAME>(<arg1>, <arg2>, ...)
#   Conditions: playerctl.Playing / playerctl.Paused / playerctl.Stopped
#               volume()
#
# NOTIFICATIONS
#     if notif from "<App>" then:
#         <action>
#     if notif contains "<word>" then:
#         <action>
#
# DISPLAY [name]
#     if <arg> then:
#         pixels -h <n,n,...>
#         pixels <64-char 01 string>
#         bright <0-15>
#         VOLUME.<mode>
#         VOLUME.<mode>(<n>)     # n rows/cols (0 = hidden, 8 = full)
#     wait <ms>
#     clear
#
#   VOLUME modes: vertical_top  vertical_bottom  horizontal_left
#                 horizontal_right  diagonal_fromRightTop
#
# Example:
#
# TRIGGERS
#     DISPLAY = onTrigger
#     VOLUME  = 200
#
# ACTIONS
#     ENCBTN:P = media_play_pause
#     ENC:+1   = volume_up(1)
#     ENC:-1   = volume_down(1)
#     if playerctl.Playing then:
#         trigger DISPLAY(playing)
#     if playerctl.Paused then:
#         trigger DISPLAY(paused)
#     if volume() then:
#         trigger DISPLAY(vol)
#
# NOTIFICATIONS
#     if notif from "Discord" then:
#         trigger DISPLAY(discord)
#
# DISPLAY
#     if playing then:
#         pixels -h 9,10,13,14,17,18,21,22,25,26,29,30,33,34,37,38,41,42,45,46,49,50,53,54
#     if paused then:
#         pixels -h 2,10,11,18,19,20,26,27,28,29,34,35,36,37,42,43,44,50,51,58
#     if discord then:
#         pixels -h 56,57,58,59,60,61,62,63
#     if vol then:
#         VOLUME.vertical_top(2)
#     wait 1000
#     clear
"""


def ensure_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG)
        print(f"Created default config at {CONFIG_FILE}")


def _strip_comment(line: str) -> str:
    in_quote = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        if ch == "#" and not in_quote:
            return line[:i].rstrip()
    return line


def _indent(line: str) -> int:
    n = 0
    for ch in line:
        if ch == "\t":
            n += 4
        elif ch == " ":
            n += 1
        else:
            break
    return n


def load_config():
    settings       = {}
    triggers       = {}
    action_rules   = []
    notif_rules    = []
    display_blocks = {}

    lines = [_strip_comment(ln) for ln in CONFIG_FILE.read_text().splitlines()]

    TOP_SECTIONS = {"TRIGGERS", "ACTIONS", "NOTIFICATIONS"}

    current_section = None
    section_name    = None
    section_body    = []  # list of (indent, text)

    def flush():
        nonlocal section_body, section_name, current_section
        if not current_section:
            return
        if current_section == "TRIGGERS":
            for _, text in section_body:
                if "=" in text:
                    k, _, v = text.partition("=")
                    v = v.strip()
                    triggers[k.strip()] = None if v.lower() == "ontrigger" else int(v)
        elif current_section == "ACTIONS":
            action_rules.extend(_parse_actions_block(section_body))
        elif current_section == "NOTIFICATIONS":
            notif_rules.extend(_parse_notif_block(section_body))
        elif current_section == "DISPLAY":
            display_blocks[section_name] = _parse_display_block(section_body)
        section_body    = []
        section_name    = None
        current_section = None

    for line in lines:
        text = line.strip()
        if not text:
            continue
        ind = _indent(line)

        if ind == 0:
            keyword = text.split()[0].upper()

            if keyword in TOP_SECTIONS:
                flush()
                current_section = keyword
                section_name    = keyword
                section_body    = []
                continue

            if keyword == "DISPLAY":
                flush()
                current_section = "DISPLAY"
                parts = text.split(None, 1)
                section_name = parts[1].strip() if len(parts) > 1 else "DISPLAY"
                section_body = []
                continue

            if "=" in text:
                flush()
                k, _, v = text.partition("=")
                settings[k.strip()] = v.strip()
                continue

        if current_section:
            section_body.append((ind, text))

    flush()
    return settings, triggers, action_rules, notif_rules, display_blocks


def _parse_actions_block(lines):
    rules = []
    i = 0
    while i < len(lines):
        ind, text = lines[i]
        i += 1

        if "=" in text and not text.lower().startswith("if "):
            k, _, v = text.partition("=")
            event = k.strip()
            if event.split(":")[0] in {"BTN", "ENC", "ENCBTN"}:
                rules.append({"type": "binding", "event": event, "action": v.strip()})
            continue

        if text.lower().startswith("if ") and text.rstrip().endswith(":"):
            condition = text[3:].rstrip(":").strip()
            if condition.lower().endswith(" then"):
                condition = condition[:-5].strip()
            body = []
            while i < len(lines) and lines[i][0] > ind:
                body.append(lines[i][1])
                i += 1
            rules.append({"type": "if", "condition": condition, "body": body})

    return rules


def _parse_notif_block(lines):
    rules = []
    i = 0
    while i < len(lines):
        ind, text = lines[i]
        i += 1

        if not text.lower().startswith("if notif "):
            continue

        rest = text[9:].rstrip(":").strip()
        if rest.lower().endswith(" then"):
            rest = rest[:-5].strip()

        match_type = value = None
        if rest.lower().startswith("from "):
            match_type = "from"
            value = rest[5:].strip().strip('"\'')
        elif rest.lower().startswith("contains "):
            match_type = "contains"
            value = rest[9:].strip().strip('"\'')

        if match_type and value:
            body = []
            while i < len(lines) and lines[i][0] > ind:
                body.append(lines[i][1])
                i += 1
            rules.append({"match": match_type, "value": value, "body": body})

    return rules


def _parse_display_block(lines):
    if_blocks = []
    tail      = []
    i = 0
    while i < len(lines):
        ind, text = lines[i]
        i += 1

        if text.lower().startswith("if ") and text.rstrip().endswith(":"):
            arg = text[3:].rstrip(":").strip()
            if arg.lower().endswith(" then"):
                arg = arg[:-5].strip()
            commands = []
            while i < len(lines) and lines[i][0] > ind:
                commands.append(lines[i][1])
                i += 1
            if_blocks.append({"arg": arg, "commands": commands})
            continue

        tail.append(text)

    return {"if_blocks": if_blocks, "tail": tail}


RP2040_VID = "2e8a"
RP2040_PID = "0005"

def find_port():
    for tty in glob.glob("/sys/class/tty/ttyACM*"):
        uevent = Path(tty) / "device" / "uevent"
        if uevent.exists():
            text = uevent.read_text().lower()
            if RP2040_VID in text and RP2040_PID in text:
                port = "/dev/" + Path(tty).name
                print(f"Found RaspDeck at {port}")
                return port
    acm = sorted(glob.glob("/dev/ttyACM*"))
    if acm:
        print(f"RP2040 VID/PID not matched; falling back to {acm[0]}")
        return acm[0]
    return None


class Display:
    """8x8 pixel framebuffer with a named layer system. Active layers are OR-ed together."""

    def __init__(self, port: serial.Serial):
        self._port   = port
        self._lock   = threading.Lock()
        self._buf    = [0] * 64
        self._layers = {}  # key -> list[int] (64 bools)

    def _send(self, msg: str):
        with self._lock:
            self._port.write((msg + "\n").encode())

    def _rebuild(self):
        merged = [0] * 64
        for layer in self._layers.values():
            for n, v in enumerate(layer):
                if v:
                    merged[n] = 1
        self._buf = merged
        self._send("pixels " + "".join(str(b) for b in self._buf))

    def activate_layer(self, key: str, pixels: list):
        self._layers[key] = pixels
        self._rebuild()

    def deactivate_layer(self, key: str):
        if key in self._layers:
            del self._layers[key]
            self._rebuild()

    def clear(self):
        self._layers = {}
        self._buf    = [0] * 64
        self._send("clear")

    def brightness(self, level: int):
        self._send(f"bright {max(0, min(15, level))}")


def _volume_pixels(mode: str, limit: int, pct: int) -> list:
    pixels = [0] * 64
    if limit == 0 or pct < 0:
        return pixels

    if mode == "vertical_top":
        max_px = limit * 8
        filled = round(pct / 100 * max_px)
        for i in range(filled):
            row, col = divmod(i, 8)
            pixels[row * 8 + col] = 1

    elif mode == "vertical_bottom":
        max_px = limit * 8
        filled = round(pct / 100 * max_px)
        for i in range(filled):
            row, col = divmod(i, 8)
            pixels[(7 - row) * 8 + col] = 1

    elif mode == "horizontal_left":
        max_px = limit * 8
        filled = round(pct / 100 * max_px)
        for i in range(filled):
            col, row = divmod(i, 8)
            pixels[row * 8 + col] = 1

    elif mode == "horizontal_right":
        max_px = limit * 8
        filled = round(pct / 100 * max_px)
        for i in range(filled):
            col, row = divmod(i, 8)
            pixels[row * 8 + (7 - col)] = 1

    elif mode == "diagonal_fromRightTop":
        order = []
        for d in range(15):
            for row in range(8):
                col = 7 - (d - row)
                if 0 <= col <= 7:
                    order.append(row * 8 + col)
        filled = round(pct / 100 * len(order))
        for idx in order[:filled]:
            pixels[idx] = 1

    else:
        print(f"[display] unknown VOLUME mode: {mode!r}")

    return pixels


# cancel tokens for volume bar fade-out: layer_key -> threading.Event
_vol_fade_cancels: dict = {}
_vol_fade_lock = threading.Lock()


def _parse_volume_cmd(cmd: str) -> tuple:
    rest = cmd[7:]  # strip "VOLUME."
    if "(" in rest and rest.endswith(")"):
        mode = rest[:rest.index("(")].strip()
        try:
            limit = int(rest[rest.index("(")+1:-1].strip())
        except ValueError:
            limit = 8
    else:
        mode  = rest.strip()
        limit = 8
    return mode, limit


def _parse_pixels_arg(rest: str):
    if rest.startswith("-h ") or rest.startswith("--human-readable "):
        idx_str = rest.split(" ", 1)[1].strip()
        pixels  = [0] * 64
        for tok in idx_str.split(","):
            tok = tok.strip()
            if tok.isdigit():
                n = int(tok)
                if 0 <= n <= 63:
                    pixels[n] = 1
        return pixels
    if len(rest) >= 64 and all(c in "01" for c in rest[:64]):
        return [int(c) for c in rest[:64]]
    return None


def run_display_block(block: dict, args: list, display: Display, layer_key: str):
    args_lower = [a.lower() for a in args]
    for ib in block["if_blocks"]:
        if ib["arg"].lower() in args_lower:
            for cmd in ib["commands"]:
                _exec_display_cmd(cmd, display, layer_key)
    _exec_tail(block["tail"], display, layer_key)


def _exec_tail(commands: list, display: Display, layer_key: str):
    i = 0
    while i < len(commands):
        cmd = commands[i].strip()
        i += 1
        if cmd.lower().startswith("wait "):
            try:
                ms = int(cmd.split()[1])
            except (IndexError, ValueError):
                continue
            remaining = commands[i:]
            def _continue(rem=remaining):
                time.sleep(ms / 1000)
                _exec_tail(rem, display, layer_key)
            threading.Thread(target=_continue, daemon=True).start()
            return  # remainder handed off to background thread
        _exec_display_cmd(cmd, display, layer_key)


def _exec_display_cmd(cmd: str, display: Display, layer_key: str):
    lower = cmd.lower()
    if lower == "clear":
        display.deactivate_layer(layer_key)
    elif lower.startswith("bright "):
        try:
            display.brightness(int(cmd.split()[1]))
        except (IndexError, ValueError):
            pass
    elif lower.startswith("pixels "):
        pixels = _parse_pixels_arg(cmd[7:].strip())
        if pixels is not None:
            display.activate_layer(layer_key, pixels)
    elif lower.startswith("volume."):
        mode, limit = _parse_volume_cmd(cmd)
        pct     = get_volume_pct()
        pixels  = _volume_pixels(mode, limit, pct)
        vol_key = layer_key + ":vol"
        display.activate_layer(vol_key, pixels)

        # cancel any existing fade-out and start a fresh 1-second one
        with _vol_fade_lock:
            old = _vol_fade_cancels.get(vol_key)
            if old:
                old.set()
            cancel = threading.Event()
            _vol_fade_cancels[vol_key] = cancel

        def _fade(c=cancel, k=vol_key):
            time.sleep(1)
            if not c.is_set():
                display.deactivate_layer(k)
                with _vol_fade_lock:
                    if _vol_fade_cancels.get(k) is c:
                        del _vol_fade_cancels[k]

        threading.Thread(target=_fade, daemon=True).start()
    else:
        print(f"[display] unknown command: {cmd!r}")


VOLUME_STEP = 5

def _pactl(*args):
    subprocess.run(["pactl", *args], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def volume_up(step: int = VOLUME_STEP):   _pactl("set-sink-volume", "@DEFAULT_SINK@", f"+{step}%")
def volume_down(step: int = VOLUME_STEP): _pactl("set-sink-volume", "@DEFAULT_SINK@", f"-{step}%")
def volume_mute(): _pactl("set-sink-mute", "@DEFAULT_SINK@", "toggle")

def get_volume_pct() -> int:
    try:
        out = subprocess.check_output(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            stderr=subprocess.DEVNULL
        ).decode()
        for part in out.split():
            if part.endswith("%"):
                return int(part.rstrip("%"))
    except Exception:
        pass
    return -1

def get_playerctl_status() -> str:
    try:
        return subprocess.check_output(
            ["playerctl", "status"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return ""

keyboard = Controller()
MEDIA_KEYS = {
    "media_play_pause": Key.media_play_pause,
    "media_next":       Key.media_next,
    "media_prev":       Key.media_previous,
    "media_stop":       Key.media_volume_mute,
}

def send_media_key(name: str):
    key = MEDIA_KEYS.get(name)
    if key:
        keyboard.press(key)
        keyboard.release(key)


_last_volume: int = -1

def _eval_condition(condition: str) -> bool:
    global _last_volume
    lower = condition.lower()
    if lower.startswith("playerctl."):
        return get_playerctl_status().lower() == condition[10:].strip().lower()
    if lower.startswith("volume(") and lower.endswith(")"):
        current = get_volume_pct()
        if current != _last_volume:
            _last_volume = current
            return True
        return False
    print(f"[actions] unknown condition: {condition!r}")
    return False


def _parse_action_arg(action: str, default: int) -> int:
    if "(" in action and action.endswith(")"):
        try:
            return int(action[action.index("(")+1:-1].strip())
        except ValueError:
            pass
    return default


def dispatch(action: str, display: Display, display_blocks: dict):
    action = action.strip()

    if action.startswith("exec="):
        subprocess.Popen(action[5:].strip(), shell=True)
    elif action.startswith("print="):
        keyboard.type(action[6:])
    elif action.startswith("log="):
        print(f"[log] {action[4:]}")
    elif action.startswith("volume_up"):
        volume_up(_parse_action_arg(action, VOLUME_STEP))
    elif action.startswith("volume_down"):
        volume_down(_parse_action_arg(action, VOLUME_STEP))
    elif action == "volume_mute":
        volume_mute()
    elif action in MEDIA_KEYS:
        send_media_key(action)
    elif action.startswith("trigger "):
        _dispatch_trigger(action[8:].strip(), display, display_blocks)
    else:
        print(f"Unknown action: {action!r}")


def _dispatch_trigger(call: str, display: Display, display_blocks: dict):
    if "(" in call and call.endswith(")"):
        name     = call[:call.index("(")].strip()
        args_str = call[call.index("(")+1:-1]
        args     = [a.strip() for a in args_str.split(",") if a.strip()]
    else:
        name = call.strip()
        args = []

    block = display_blocks.get(name)
    if block is None:
        print(f"[trigger] unknown display block: {name!r}")
        return

    threading.Thread(
        target=run_display_block,
        args=(block, args, display, f"display:{name}"),
        daemon=True
    ).start()


def _start_notif_watcher(notif_queue: queue.Queue):
    try:
        import dbus
        import dbus.mainloop.glib
        from gi.repository import GLib
    except ImportError:
        print("[notif] dbus-python / PyGObject not found — "
              "NOTIFICATIONS section will be ignored. "
              "Install with: pip install dbus-python")
        return

    def run():
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()

        def on_notify(sender, dest, iface, member, path, msg):
            if iface != "org.freedesktop.Notifications" or member != "Notify":
                return
            try:
                app_name = str(msg[0])
                summary  = str(msg[3]) if len(msg) > 3 else ""
                body     = str(msg[4]) if len(msg) > 4 else ""
                notif_queue.put((app_name, summary + " " + body))
            except Exception:
                pass

        bus.add_match_string(
            "type='method_call',"
            "interface='org.freedesktop.Notifications'"
        )
        bus.add_message_filter(on_notify)
        GLib.MainLoop().run()

    threading.Thread(target=run, daemon=True).start()


def _run_notif_rules(notif_rules: list, app_name: str, text: str,
                     display: Display, display_blocks: dict):
    for rule in notif_rules:
        if rule["match"] == "from":
            matched = app_name.lower() == rule["value"].lower()
        else:
            matched = rule["value"].lower() in text.lower()
        if matched:
            for action in rule["body"]:
                dispatch(action.strip(), display, display_blocks)


def reader_thread(ser: serial.Serial, event_queue: queue.Queue):
    while True:
        try:
            line = ser.readline().decode(errors="replace").strip()
            if line:
                event_queue.put(("serial", line))
        except serial.SerialException:
            print("Serial connection lost.")
            event_queue.put(("quit", None))
            break
        except Exception as e:
            print(f"Reader error: {e}")
            time.sleep(0.1)


def main():
    ensure_config()
    settings, triggers, action_rules, notif_rules, display_blocks = load_config()

    port = settings.get("PORT") or find_port()
    if not port:
        print("No RaspDeck device found. Plug it in and try again.")
        sys.exit(1)

    try:
        ser = serial.Serial(port, 115200, timeout=1)
    except serial.SerialException as e:
        print(f"Could not open {port}: {e}")
        sys.exit(1)

    time.sleep(0.5)

    display = Display(ser)

    try:
        display.brightness(int(settings.get("BRIGHT", 8)))
    except ValueError:
        pass

    display.clear()
    print(f"RaspDeck connected on {port}.")
    print("Listening for events. Ctrl-C to quit.")

    event_queue: queue.Queue = queue.Queue()
    notif_queue: queue.Queue = queue.Queue()

    threading.Thread(target=reader_thread, args=(ser, event_queue), daemon=True).start()

    if notif_rules:
        _start_notif_watcher(notif_queue)

    for name, interval_ms in triggers.items():
        if interval_ms is None:
            continue
        if name == "VOLUME":
            def _vol_poll(ms=interval_ms):
                global _last_volume
                while True:
                    time.sleep(ms / 1000)
                    current = get_volume_pct()
                    if current != _last_volume:
                        _last_volume = current
                        for rule in condition_rules:
                            try:
                                cond = rule["condition"].lower()
                                if cond.startswith("volume(") and cond.endswith(")"):
                                    for action in rule["body"]:
                                        dispatch(action.strip(), display, display_blocks)
                            except Exception as e:
                                print(f"Volume poll error: {e}")
            threading.Thread(target=_vol_poll, daemon=True).start()
        else:
            block = display_blocks.get(name)
            if block:
                def _poll(b=block, n=name, ms=interval_ms):
                    while True:
                        time.sleep(ms / 1000)
                        run_display_block(b, [], display, f"display:{n}")
                threading.Thread(target=_poll, daemon=True).start()

    bindings: dict[str, list[str]] = {}
    for rule in action_rules:
        if rule["type"] == "binding":
            bindings.setdefault(rule["event"], []).append(rule["action"])

    condition_rules = [r for r in action_rules if r["type"] == "if"]

    try:
        while True:
            while not notif_queue.empty():
                try:
                    app_name, text = notif_queue.get_nowait()
                    _run_notif_rules(notif_rules, app_name, text, display, display_blocks)
                except queue.Empty:
                    break

            # 500ms timeout keeps the notif queue responsive
            try:
                kind, data = event_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if kind == "quit":
                break

            actions = bindings.get(data, [])
            if actions:
                for action in actions:
                    try:
                        dispatch(action, display, display_blocks)
                    except Exception as e:
                        print(f"Action error for {data!r}: {e}")
            else:
                print(f"Unbound event: {data}")

            for rule in condition_rules:
                try:
                    if _eval_condition(rule["condition"]):
                        for action in rule["body"]:
                            dispatch(action.strip(), display, display_blocks)
                except Exception as e:
                    print(f"Condition error: {e}")

    except KeyboardInterrupt:
        print("\nQuitting.")
    finally:
        display.clear()
        ser.close()


if __name__ == "__main__":
    main()
