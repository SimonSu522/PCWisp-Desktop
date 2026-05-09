# PcWisp Desktop Client

PcWisp is a cross-platform desktop client that lets you instantly sync text and transfer files from your phone to your PC over your local Wi-Fi network — no cables, no cloud.

---

## Features

- 📋 Automatically pastes text sent from your phone into the active window
- 📁 Receives files from your phone and saves them to your Downloads folder
- 🔍 Discovers your phone automatically via mDNS (no manual IP setup required)
- 💻 Supports Windows, macOS, and Linux (X11 & Wayland)

---

## Requirements

### Windows & macOS
```
pip install -r requirements.txt
```

### Linux (Ubuntu)
```bash
pip install -r requirements.txt

# X11 users:
sudo apt install xdotool xclip

# Wayland users:
sudo apt install ydotool wl-clipboard
```

---

## Run from Source

```bash
python PCWisp.py
```

---

## Build Executable

Make sure PyInstaller is installed:
```bash
pip install pyinstaller
```

### Windows
```bash
pyinstaller --onefile --windowed --name PCWisp-windows PCWisp.py
```

### macOS
```bash
pyinstaller --onefile --windowed --name PCWisp-macos PCWisp.py
```

### Linux
```bash
pyinstaller --onefile --windowed --name PCWisp-ubuntu PCWisp.py
chmod +x dist/PCWisp-ubuntu
```

The output executable will be located in the `dist/` folder.

---

## Download Pre-built Executables

If you don't want to build from source, pre-built executables for all platforms are available on the [Releases](../../releases) page.

---

## How It Works

1. Launch PcWisp on your desktop
2. Open the PcWisp app on your phone
3. Both devices must be on the **same Wi-Fi network**
4. The desktop client discovers your phone automatically and connects
5. Send text or files from your phone — they appear on your PC instantly

---

## License

MIT License. Feel free to use, modify, and distribute.
