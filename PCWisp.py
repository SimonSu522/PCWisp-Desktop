import socket
import threading
import json
import time
import tkinter as tk
import subprocess
import platform
import sys
import os
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

# ── Detect operating system ───────────────────────────────
OS = platform.system()   # "Windows" | "Darwin" | "Linux"

# Windows only: conditionally import winreg
if OS == "Windows":
    import winreg

# Windows / macOS shared: conditionally import pyperclip & pyautogui
if OS in ("Windows", "Darwin"):
    import pyperclip
    import pyautogui

SERVICE_TYPE = "_pcwisp._tcp.local."
PORT = 9999


# ═══════════════════════════════════════════════════════════
#  1. Linux only: Wayland / X11 detection and ydotoold
# ═══════════════════════════════════════════════════════════

def _detect_session():
    """Detect the Linux display protocol; returns 'wayland' or 'x11'."""
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland":
        return "wayland"
    if session == "x11":
        return "x11"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "x11"

SESSION_TYPE = _detect_session() if OS == "Linux" else None

if OS == "Linux":
    print(f"🖥️  Display protocol: {SESSION_TYPE.upper()}")


def ensure_ydotoold():
    """
    [Linux / Wayland only]
    Ensure the ydotoold background service is running.
    Tries systemd user service first; falls back to launching the process directly.
    """
    if OS != "Linux" or SESSION_TYPE != "wayland":
        return

    result = subprocess.run(["pgrep", "-x", "ydotoold"], capture_output=True)
    if result.returncode == 0:
        print("✅ ydotoold is already running")
        return

    r = subprocess.run(
        ["systemctl", "--user", "start", "ydotoold"],
        capture_output=True
    )
    if r.returncode == 0:
        print("✅ ydotoold started via systemd")
        time.sleep(0.5)
        return

    try:
        subprocess.Popen(
            ["ydotoold"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("✅ ydotoold launched directly (background)")
        time.sleep(0.8)   # Wait for socket to become available
    except FileNotFoundError:
        print("❌ ydotoold not found. Please run: sudo apt install ydotool")


# ═══════════════════════════════════════════════════════════
#  2. Cross-platform: resolve the Downloads folder path
# ═══════════════════════════════════════════════════════════

def get_downloads_folder():
    if OS == "Windows":
        # Read the user-configured Downloads path from the Registry
        try:
            sub_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
                path, _ = winreg.QueryValueEx(
                    key, "{374DE290-123F-4565-9164-39C4925E467B}"
                )
                return path
        except Exception:
            pass  # Fall through to default on failure

    elif OS == "Linux":
        # Use xdg-user-dir to respect the user's configured Downloads path
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DOWNLOAD"],
                capture_output=True, text=True, timeout=3
            )
            path = result.stdout.strip()
            if path and os.path.isdir(path):
                return path
        except Exception:
            pass

    # Default fallback for macOS and any failure above
    return os.path.join(os.path.expanduser("~"), "Downloads")


# ═══════════════════════════════════════════════════════════
#  3. Cross-platform: clipboard write and paste simulation
# ═══════════════════════════════════════════════════════════

def _copy_to_clipboard(text):
    """Write text to the system clipboard (platform-specific implementation)."""
    if OS == "Windows":
        pyperclip.copy(text)
        time.sleep(0.3)   # Windows clipboard write needs a slightly longer delay

    elif OS == "Darwin":
        pyperclip.copy(text)
        time.sleep(0.2)

    elif OS == "Linux":
        if SESSION_TYPE == "wayland":
            subprocess.run(
                ["wl-copy"],
                input=text.encode("utf-8"),
                check=True
            )
        else:
            # X11: prefer xclip, fall back to xsel
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    check=True
                )
            except FileNotFoundError:
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode("utf-8"),
                    check=True
                )


def _send_paste_keystroke():
    """Simulate Ctrl+V / Cmd+V (platform-specific implementation)."""
    if OS == "Windows":
        pyautogui.keyDown('ctrl')
        time.sleep(0.05)
        pyautogui.press('v')
        time.sleep(0.05)
        pyautogui.keyUp('ctrl')

    elif OS == "Darwin":
        pyautogui.keyDown('command')
        time.sleep(0.05)
        pyautogui.press('v')
        time.sleep(0.05)
        pyautogui.keyUp('command')

    elif OS == "Linux":
        if SESSION_TYPE == "wayland":
            result = subprocess.run(
                ["ydotool", "key", "ctrl+v"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip())
        else:
            try:
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                    check=True
                )
            except FileNotFoundError:
                # Fall back to pyautogui if xdotool is unavailable
                import pyautogui as _pag
                _pag.hotkey("ctrl", "v")


def perform_paste(text):
    """Full copy-then-paste flow shared across all platforms."""
    if not text:
        return
    try:
        _copy_to_clipboard(text)
        _send_paste_keystroke()
        flash_status("✅ Text pasted")
    except Exception as e:
        print(f"Paste failed: {e}")
        # Text is still on the clipboard even if the keystroke simulation failed
        flash_status("⚠️ Copied — please paste manually with Ctrl+V", "#FF9500")


# ═══════════════════════════════════════════════════════════
#  4. Cross-platform: safe filename sanitisation
# ═══════════════════════════════════════════════════════════

def _sanitize_filename(file_name):
    """Strip characters that are illegal in filenames on the current platform."""
    if OS == "Windows":
        invalid = r'\/:*?"<>|'
        safe = "".join(c for c in file_name if c not in invalid).strip()
    else:
        # macOS / Linux: disallow forward slash and null byte
        safe = file_name.replace('/', '_').replace('\x00', '_').strip()

    return safe or "received_file"


# ═══════════════════════════════════════════════════════════
#  5. Core logic: PcWispClient (shared across all platforms)
# ═══════════════════════════════════════════════════════════

class PcWispClient:
    def __init__(self, root):
        self.root = root
        self.socket = None
        self.connected = False
        self.target_ip = None

    def start_discovery(self):
        self.zeroconf = Zeroconf()
        self.listener = MyListener(self)
        self.browser = ServiceBrowser(self.zeroconf, SERVICE_TYPE, self.listener)
        update_status("🔍 Scanning for phone...", "#FF9500")

    def on_device_found(self, ip):
        if self.connected:
            return
        self.target_ip = ip
        update_status(f"📱 Phone found ({ip}), connecting...", "#007AFF")
        threading.Thread(target=self.connect_to_phone, args=(ip,), daemon=True).start()

    def connect_to_phone(self, ip):
        while not self.connected:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(5)
                self.socket.connect((ip, PORT))
                self.socket.settimeout(None)
                self.connected = True
                self.root.after(0, lambda: update_status(f"✅ Connected to phone ({ip})", "#28a745"))
                self.receive_loop()
            except Exception as e:
                print(f"Connection failed: {e}")
                time.sleep(3)

    def receive_loop(self):
        """Dispatch incoming data as either plain text or binary file (shared logic)."""
        try:
            f = self.socket.makefile('rb')

            while self.connected:
                # 1. Read the newline-terminated JSON header
                line = f.readline()
                if not line:
                    break

                try:
                    payload = json.loads(line.decode('utf-8').strip())
                except Exception as e:
                    print(f"Header parse error: {e}")
                    continue

                # 2. Route by message type
                msg_type = payload.get('type')

                if msg_type == 'PLAIN_TEXT':
                    content = payload.get('content', '')
                    self.root.after(0, lambda c=content: perform_paste(c))

                elif msg_type == 'FILE':
                    file_name = payload.get('fileName')
                    file_size = payload.get('fileSize')
                    print(f"📥 Receiving file: {file_name} ({file_size} bytes)")
                    self.receive_file_content(f, file_name, file_size)

        except Exception as e:
            print(f"Disconnected or error: {e}")
        finally:
            self.connected = False
            self.socket.close()
            self.root.after(0, lambda: update_status("❌ Phone disconnected. Reconnecting...", "#dc3545"))
            if self.target_ip:
                threading.Thread(
                    target=self.connect_to_phone,
                    args=(self.target_ip,),
                    daemon=True
                ).start()

    def receive_file_content(self, sock_file, file_name, file_size):
        """Receive a binary stream and save it to the Downloads folder (shared logic)."""
        try:
            downloads_path = get_downloads_folder()
            safe_name = _sanitize_filename(file_name)
            save_path = os.path.join(downloads_path, safe_name)

            # Auto-number duplicates to avoid overwriting existing files
            base, ext = os.path.splitext(save_path)
            counter = 1
            while os.path.exists(save_path):
                save_path = f"{base}({counter}){ext}"
                counter += 1

            remaining = file_size
            with open(save_path, 'wb') as out_f:
                while remaining > 0:
                    chunk = sock_file.read(min(remaining, 8192))
                    if not chunk:
                        break
                    out_f.write(chunk)
                    remaining -= len(chunk)

            final_name = os.path.basename(save_path)
            self.root.after(0, lambda: flash_status(f"📁 File saved to Downloads: {final_name}", "#007AFF"))
            print(f"✅ File received: {save_path}")
        except Exception as e:
            print(f"File save failed: {e}")


# ═══════════════════════════════════════════════════════════
#  6. Zeroconf Listener
# ═══════════════════════════════════════════════════════════

class MyListener(ServiceListener):
    def __init__(self, client_app):
        self.client_app = client_app

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info:
            ip = socket.inet_ntoa(info.addresses[0])
            self.client_app.on_device_found(ip)

    def update_service(self, *args):
        pass

    def remove_service(self, *args):
        pass


# ═══════════════════════════════════════════════════════════
#  7. GUI helper functions
# ═══════════════════════════════════════════════════════════

def update_status(text, color):
    status_label.config(text=text, fg=color)


def flash_status(text, color="#28a745"):
    original = status_label.cget("text")
    orig_color = status_label.cget("fg")
    status_label.config(text=text, fg=color)
    root.after(3000, lambda: status_label.config(text=original, fg=orig_color))


def on_closing():
    sys.exit()


# ═══════════════════════════════════════════════════════════
#  8. Startup (Linux must ensure ydotoold is running first)
# ═══════════════════════════════════════════════════════════

if OS == "Linux":
    threading.Thread(target=ensure_ydotoold, daemon=True).start()

# ── GUI ──────────────────────────────────────────────────

# Choose a platform-appropriate font
_FONT = {
    "Windows": "Segoe UI",
    "Darwin":  "Arial",
    "Linux":   "Ubuntu",
}.get(OS, "Arial")

root = tk.Tk()
root.title("PcWisp (Client Mode)")
root.geometry("350x270")
root.configure(bg="#F5F5F7")

tk.Label(
    root,
    text="PcWisp Desktop",
    font=(_FONT, 16, "bold"),
    bg="#F5F5F7"
).pack(pady=15)

status_label = tk.Label(
    root,
    text="Initialising...",
    font=(_FONT, 10),
    bg="#F5F5F7",
    fg="#888",
    wraplength=300
)
status_label.pack(pady=10)

# Linux only: show the active display protocol
if OS == "Linux":
    session_color = "#007AFF" if SESSION_TYPE == "wayland" else "#28a745"
    tk.Label(
        root,
        text=f"Display protocol: {SESSION_TYPE.upper()}",
        font=(_FONT, 8),
        bg="#F5F5F7",
        fg=session_color
    ).pack()

tk.Label(
    root,
    text="Supports text sync and file transfer\nFiles are saved to your Downloads folder",
    font=(_FONT, 9),
    bg="#F5F5F7",
    fg="#aaa"
).pack(side="bottom", pady=15)

client = PcWispClient(root)
threading.Thread(target=client.start_discovery, daemon=True).start()
root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()
