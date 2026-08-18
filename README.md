# ScannerHub

Local barcode / QR logger for a laptop camera and a USB or Bluetooth scanner (the kind that types like a keyboard).

Every scan is saved with a timestamp and where it came from (camera vs hardware scanner). There is a small web dashboard for live scans, camera preview, stats, and sound settings.

It is meant to be started by hand. Nothing runs in the background or at login.

Works on **Linux** and **Windows**. The dashboard opens the webcam in the browser (you get the usual Allow prompt). USB scanners are read by the Python backend.

---

## What you need

- Python 3.11 or newer
- A webcam (built-in or USB) if you want camera scanning
- A HID barcode scanner if you want hardware scans (optional)

On **Debian / Ubuntu / similar**:

```bash
sudo apt install -y python3 python3-venv python3-pip libgl1
```

`libzbar0` is optional. Camera scanning is done in the browser. Install `libzbar0` only if you also want the Python backend to decode uploaded frames.

On **Windows**:

- Install Python from python.org and tick **Add python.exe to PATH**
- `pyzbar` ships its own zbar DLL, so you usually do not need extra barcode libraries
- A camera driver that OpenCV can open (most USB webcams are fine)

---

## Install

```bash
git clone https://github.com/sohaib1khan/ScannerHub.git
cd ScannerHub

python3 -m venv .venv
```

Linux / macOS:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Windows (cmd):

```bat
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

If PowerShell blocks the activate script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## Run

From the repo root, with the venv active:

```bash
python backend/app.py
```

Default URL is **http://127.0.0.1:8765/**

### Change the port

If 8765 is already taken, pick another port. Easiest: copy `.env.example` to `.env` and edit it:

```bash
cp .env.example .env
```

```
SCANNERHUB_HOST=127.0.0.1
SCANNERHUB_PORT=9000
```

Then run `python backend/app.py` as usual. Or set it for one run:

```bash
SCANNERHUB_PORT=9000 python backend/app.py
python backend/app.py --port 9000
```

Order of precedence: `--port` flag, then `SCANNERHUB_PORT` in the environment / `.env`, then `api_port` in `data/settings.json`, then 8765.

Useful flags:

```bash
python backend/app.py --open
python backend/app.py --host 127.0.0.1 --port 9000
```

`--open` launches the dashboard in your default browser. A packaged build does that on its own.

Check that the API is up (use the same port you started with):

```bash
curl http://127.0.0.1:8765/api/health
```

You want `"status": "ok"`.

### On the dashboard

1. Click **Start camera**. The browser will pop up a permission prompt — choose **Allow**.
2. You should see a live preview. If it says blocked, click **Allow camera** again, or the camera icon in the address bar, and set this site to Allow.
3. Hold a QR or barcode inside the green box. It should show up in the live feed and in `data/scan_history.json`.
4. For a USB scanner: click the **Hardware scanner input** box and scan. If Linux blocked the global keyboard hook, this box is the way in (see below).
5. Sounds and the duplicate-scan window are under Settings.

Use localhost (`127.0.0.1`), not a LAN IP. Browsers will not offer a camera prompt on a random hostname unless you use HTTPS.

If the camera light was on but the preview was black, that was the backend holding the webcam. Starting the camera from the dashboard now uses the browser camera instead.

Scan history, settings, and default beep files live in `data/` next to the project (or next to the exe if you built one).

---

## Linux: USB scanner permissions

A lot of USB scanners pretend to be a keyboard. ScannerHub tries to catch that burst of keystrokes.

On Linux that usually needs root:

```bash
sudo .venv/bin/python backend/app.py
```

If you do not want to run as root, leave the backend as a normal user and scan into the dashboard input field instead. The status pill will say to use the input field when the hook is unavailable.

---

## Optional: dashboard in Docker

Only useful while developing. Hardware still has to run on the host, so start the Python backend first, then:

```bash
cd frontend
docker compose up --build
```

Dashboard: **http://127.0.0.1:8080/**

That container proxies `/api` to the backend on the host (default port 8765 in `frontend/nginx.conf`). If you changed `SCANNERHUB_PORT`, update that nginx file to match. You do not need Docker to use the app day to day.

---

## Tests

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pytest tests
```

These do not need a camera.

---

## Build a standalone exe

Linux:

```bash
pyinstaller packaging/pyinstaller_linux.spec
```

Windows:

```bat
pyinstaller packaging/pyinstaller_windows.spec
```

Output is `dist/ScannerHub` or `dist/ScannerHub.exe`. Copy that file to the other machine. No Python install on that machine. Data still goes in a `data/` folder next to the executable.

---

## How it fits together

```
camera (OpenCV + pyzbar)  ─┐
                           ├─► scan handler ─► data/scan_history.json
USB scanner (keystrokes)  ─┘         │
                                     ▼
                          local API  (REST + WebSocket)
                                     │
                                     ▼
                          dashboard in the browser
```

- Camera and scanner stay native. Docker cannot reliably own USB cameras on Windows, and it is flaky on Linux too.
- The dashboard never talks to hardware. It only calls the API.
- Same barcode scanned twice within 2 seconds is ignored (camera would otherwise spam the log). You can change that in Settings.
- Supported codes are whatever pyzbar gives you by default: QR, EAN, UPC, Code 128, and similar.

---

## API (if you are poking at it)

| Method | Path | What it does |
| ------ | ---- | ------------ |
| GET | `/api/health` | Is the process up |
| GET | `/api/status` | Camera, scanner hook, counts |
| GET | `/api/cameras` | Cameras with names when the OS has them |
| POST | `/api/camera/select` | Choose a camera and start it |
| GET | `/api/camera/preview` | MJPEG preview |
| GET | `/api/scans` | History |
| POST | `/api/scans/manual` | Typed / HID-fallback scan |
| WS | `/api/ws/scans` | Live events |
| GET/POST | `/api/settings` | Camera, HID, dedupe, sounds |

Same routes exist without the `/api` prefix (`/health`, `/cameras`, …).

---

## Layout

```
backend/          Python app (camera, scanner, API, sounds, log)
frontend/         dashboard (also has Docker files for local UI work)
data/             created at runtime (log, settings, sounds)
packaging/        PyInstaller specs
tests/
```

Not in git: `.venv/`, `data/scan_history.json`, `data/settings.json`, generated wavs, `dist/`.
