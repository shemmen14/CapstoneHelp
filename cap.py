# Program to operate camera and motion sensor for Raspberry Pi
# - Sam Hemmen

import os, time, threading, subprocess, shlex, shutil, logging
from datetime import datetime
import RPi.GPIO as GPIO
import csv

# ---------- LOGGING ----------
# Quiet down Flask/Werkzeug request spam ("GET / HTTP/1.1" 200 -)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# ---------- PLOTTING IMPORTS ----------
try:
    import matplotlib
    matplotlib.use("Agg")  # non-GUI backend
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:
    HAS_MPL = False

# ---------- WEB DASHBOARD IMPORTS ----------
try:
    from flask import (
        Flask,
        send_from_directory,
        jsonify,
        render_template_string,
        Response,
        redirect,
        url_for,
    )
    HAS_FLASK = True
except Exception:
    HAS_FLASK = False

# ---------- OPENCV (LIVESTREAM) IMPORT ----------
try:
    import cv2
    HAS_OPENCV = True
except Exception:
    HAS_OPENCV = False

# ---------- PATHS / DATA DIR ----------
DATA_DIR = os.path.expanduser("~/CapstoneData")
LOG_FILE = os.path.join(DATA_DIR, "motion_log.csv")
GRAPH_FILE = os.path.join(DATA_DIR, "motion_intervals.png")

# ---------- GOOGLE DRIVE UPLOAD (rclone) ----------
GOOGLE_DRIVE_REMOTE = "T9P50:sumdiff"  # rclone remote:path
HAS_RCLONE = shutil.which("rclone") is not None

# ---------- SETTINGS ----------
PIR_PIN = 17                          # BCM pin for PIR OUT
RECORD_SECONDS = 5                    # clip length
COOLDOWN_SECONDS = 30                 # min time between triggers

DEVICE = "/dev/video0"                # USB Arducam device
WIDTH, HEIGHT, FPS = 1920, 1080, 30
INPUT_FORMAT = "mjpeg"
ENCODER = "h264_v4l2m2m"              # try HW encoder; fallback to libx264 automatically
BITRATE = "6M"

# ---------- STATE ----------
last_trigger = 0.0                    # monotonic timestamp of last *recording* trigger
record_lock = threading.Lock()

last_motion_timestamp = None          # human-readable string
last_motion_delta = None              # seconds since previous motion
motion_event_count = 0

KILL_REQUESTED = False                # for web kill switch

# NEW: camera mode - "record" or "stream"
CAMERA_MODE = "record"                # default mode


# ---------- UTILS ----------
def run_cmd(cmd):
    return subprocess.run(
        shlex.split(cmd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

def upload_to_drive(path):
    """Upload a single file to Google Drive using rclone, if available."""
    if not HAS_RCLONE:
        return
    if not os.path.exists(path):
        return
    try:
        cmd = f"rclone copy {shlex.quote(path)} {GOOGLE_DRIVE_REMOTE}"
        res = run_cmd(cmd)
        if res.returncode != 0:
            print(f"rclone upload error for {path}:\n", res.stderr.strip() or res.stdout.strip())
    except Exception as e:
        print(f"rclone exception for {path}: {e}")


# ---------- FFMPEG RECORDING ----------
def ffmpeg_cmd(outpath):
    # FFmpeg command for a 5s capture from a UVC cam
    base = (
        f'ffmpeg -hide_banner -loglevel error -y '
        f'-f v4l2 -framerate {FPS} -video_size {WIDTH}x{HEIGHT} '
        f'-input_format {INPUT_FORMAT} -i {DEVICE} '
        f'-t {RECORD_SECONDS} '
        f'-pix_fmt yuv420p '
    )

    if shutil.which("ffmpeg"):
        # try hardware encoder
        cmd = base + f'-c:v {ENCODER} -b:v {BITRATE} {shlex.quote(outpath)}'
        test = run_cmd(cmd)
        if test.returncode == 0:
            return cmd

        # fallback to libx264
        return base + f'-c:v libx264 -preset veryfast -crf 23 {shlex.quote(outpath)}'
    else:
        raise RuntimeError("ffmpeg not found")

def record_clip():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(DATA_DIR, f"motion_{ts}.mp4")
    print(f"[{ts}] Recording {RECORD_SECONDS}s -> {out}")

    cmd = ffmpeg_cmd(out)
    res = run_cmd(cmd)
    if res.returncode != 0:
        print("FFmpeg error:\n", res.stderr.strip() or res.stdout.strip())
    else:
        print(f"[{ts}] Saved {out}")
        # upload video to Google Drive
        upload_to_drive(out)


# ---------- CHART GENERATION ----------
def update_interval_chart():
    """Read motion_log.csv and generate a PNG chart of intervals between motions."""
    if not HAS_MPL or not os.path.exists(LOG_FILE):
        return

    indices, deltas = [], []

    try:
        with open(LOG_FILE, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                delta_str = row.get("seconds_since_last_motion")
                if not delta_str or delta_str == "None":
                    continue
                try:
                    val = float(delta_str)
                except ValueError:
                    continue
                deltas.append(val)
                indices.append(len(deltas))
    except Exception:
        return

    if not deltas:
        return

    plt.figure()
    plt.plot(indices, deltas, marker="o")
    plt.xlabel("Motion event index")
    plt.ylabel("Seconds since previous motion")
    plt.title("Intervals Between Motion Events")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.tight_layout()

    try:
        plt.savefig(GRAPH_FILE)
    finally:
        plt.close()

    # upload graph to Google Drive
    upload_to_drive(GRAPH_FILE)


# ---------- CSV LOGGING ----------
def log_motion(timestamp, delta):
    """Append motion detection timestamp + time since last motion to CSV and update chart."""
    new_file = not os.path.exists(LOG_FILE)
    try:
        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(["timestamp", "seconds_since_last_motion"])
            writer.writerow([timestamp, delta])
    except Exception as e:
        print("Log write error:", e)
        return

    # upload CSV to Google Drive
    upload_to_drive(LOG_FILE)

    # update chart after logging
    update_interval_chart()


# ---------- MOTION HANDLER ----------
def on_motion(_ch):
    global last_trigger, last_motion_timestamp, last_motion_delta, motion_event_count, CAMERA_MODE

    now = time.monotonic()

    # calculate delta BEFORE updating trigger time
    if last_motion_timestamp is None:
        delta = None  # first detection
    else:
        delta = round(now - last_trigger, 3)

    # human-readable timestamp
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # update dashboard state
    last_motion_timestamp = timestamp_str
    last_motion_delta = delta
    motion_event_count += 1

    # print to terminal
    mode_str = CAMERA_MODE.upper()
    if delta is None:
        print(f"[{timestamp_str}] Motion detected (first event). [Mode={mode_str}]")
    else:
        print(f"[{timestamp_str}] Motion detected. Δt = {delta} s. [Mode={mode_str}]")

    # log every detection
    log_motion(timestamp_str, delta)

    # cooldown check for recording
    if (now - last_trigger) < COOLDOWN_SECONDS:
        return
    last_trigger = now

    # Only record in RECORD mode
    if CAMERA_MODE != "record":
        return

    def worker():
        with record_lock:
            try:
                record_clip()
            except Exception as e:
                print("Recording error:", e)

    threading.Thread(target=worker, daemon=True).start()


# ---------- WEB DASHBOARD & LIVESTREAM ----------
app = Flask(__name__) if HAS_FLASK else None

DASHBOARD_TEMPLATE = """
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Capstone Motion Dashboard</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        .card { border: 1px solid #ccc; border-radius: 8px; padding: 16px; max-width: 900px; }
        h1 { margin-top: 0; }
        img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }
        dt { font-weight: bold; }
        button.kill {
            padding: 10px 20px;
            font-size: 16px;
            background: #c0392b;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            margin-top: 12px;
        }
        .row { display: flex; flex-wrap: wrap; gap: 16px; }
        .col { flex: 1 1 280px; }
        .mode-btn {
            padding: 6px 12px;
            margin-right: 6px;
            border-radius: 4px;
            border: 1px solid #888;
            cursor: pointer;
            background: #eee;
        }
        .mode-btn.active {
            background: #2c3e50;
            color: #fff;
            border-color: #2c3e50;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>Capstone Motion Dashboard</h1>

        <p>Current camera mode:
            <strong id="modeText">{{ current_mode.upper() }}</strong>
        </p>
        <form action="/mode/record" method="get" style="display:inline;">
            <button class="mode-btn {% if current_mode == 'record' %}active{% endif %}">
                Record Mode
            </button>
        </form>
        <form action="/mode/stream" method="get" style="display:inline;">
            <button class="mode-btn {% if current_mode == 'stream' %}active{% endif %}">
                Stream Mode
            </button>
        </form>

        <div class="row" style="margin-top:16px;">
            <div class="col">
                <h2>Status</h2>
                <dl>
                    <dt>Last motion timestamp</dt>
                    <dd id="lastMotion">{{ last_motion_timestamp or "No motion yet" }}</dd>

                    <dt>Seconds since previous motion</dt>
                    <dd id="deltaMotion">
                        {% if last_motion_delta is none %}
                            N/A
                        {% else %}
                            {{ last_motion_delta }} s
                        {% endif %}
                    </dd>

                    <dt>Total motion events (since script start)</dt>
                    <dd id="eventCount">{{ motion_event_count }}</dd>
                </dl>

                <h2>Controls</h2>
                <form action="/kill" method="get">
                    <button class="kill">STOP PROGRAM</button>
                </form>
            </div>

            <div class="col">
                <h2>Live Camera Stream</h2>
                {% if livestream_available and current_mode == 'stream' %}
                    <img id="liveStream" src="/livestream" alt="Live camera stream">
                    <p style="font-size:12px;color:#555;">
                        Stream is active in STREAM mode. Switch to RECORD mode to enable clip recording.
                    </p>
                {% elif current_mode != 'stream' %}
                    <p>Switch to STREAM mode to enable live video.</p>
                {% else %}
                    <p>OpenCV not installed or camera unavailable.</p>
                {% endif %}
            </div>
        </div>

        <h2>Intervals Between Motions</h2>
        {% if graph_exists %}
            <img id="intervalGraph" src="/graph" alt="Motion intervals graph">
        {% else %}
            <p>No interval graph yet. It will appear after a few motion events.</p>
        {% endif %}
    </div>

    <script>
        async function refreshData() {
            try {
                const res = await fetch('/data');
                if (!res.ok) return;
                const data = await res.json();

                // Update text fields
                document.getElementById('lastMotion').textContent =
                    data.last_motion_timestamp || 'No motion yet';

                document.getElementById('eventCount').textContent =
                    data.motion_event_count;

                if (data.last_motion_delta === null || data.last_motion_delta === undefined) {
                    document.getElementById('deltaMotion').textContent = 'N/A';
                } else {
                    document.getElementById('deltaMotion').textContent =
                        data.last_motion_delta + ' s';
                }

                // Mode text (this won't toggle buttons, but keeps label correct)
                if (data.current_mode) {
                    document.getElementById('modeText').textContent = data.current_mode.toUpperCase();
                }

                // Bust cache on graph so it updates as the file changes
                const graph = document.getElementById('intervalGraph');
                if (graph) {
                    const baseSrc = '/graph';
                    graph.src = baseSrc + '?t=' + Date.now();
                }
            } catch (e) {
                // silently ignore errors
            }
        }

        // Poll every 3 seconds
        setInterval(refreshData, 3000);
        refreshData();
    </script>
</body>
</html>
"""

def gen_frames():
    """Generator that yields JPEG frames from the USB camera for livestream.

    Only active while CAMERA_MODE == "stream" and KILL_REQUESTED is False.
    Uses the V4L2 backend to avoid GStreamer pipeline issues.
    """
    if not HAS_OPENCV:
        return

    global KILL_REQUESTED, CAMERA_MODE

    # Open camera with V4L2 backend
    cap = cv2.VideoCapture(DEVICE, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 15)

    if not cap.isOpened():
        print("[Livestream] Failed to open camera with V4L2 backend.")
        cap.release()
        return

    print("[Livestream] Streaming started (V4L2 backend).")

    while True:
        if KILL_REQUESTED or CAMERA_MODE != "stream":
            break

        success, frame = cap.read()
        if not success:
            # brief backoff if frame read fails
            time.sleep(0.05)
            continue

        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue
        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )

    cap.release()
    print("[Livestream] Streaming stopped (mode changed or kill).")



if HAS_FLASK:
    @app.route("/")
    def index():
        return render_template_string(
            DASHBOARD_TEMPLATE,
            last_motion_timestamp=last_motion_timestamp,
            last_motion_delta=last_motion_delta,
            motion_event_count=motion_event_count,
            graph_exists=os.path.exists(GRAPH_FILE),
            livestream_available=HAS_OPENCV,
            current_mode=CAMERA_MODE,
        )

    @app.route("/graph")
    def graph():
        if not os.path.exists(GRAPH_FILE):
            return "No graph yet", 404
        return send_from_directory(os.path.dirname(GRAPH_FILE),
                                   os.path.basename(GRAPH_FILE))

    @app.route("/data")
    def data():
        return jsonify(
            last_motion_timestamp=last_motion_timestamp,
            last_motion_delta=last_motion_delta,
            motion_event_count=motion_event_count,
            current_mode=CAMERA_MODE,
        )

    @app.route("/kill")
    def kill():
        global KILL_REQUESTED
        KILL_REQUESTED = True
        return "<h1>Kill signal sent. Program will shut down.</h1>", 200

    @app.route("/mode/<mode>")
    def set_mode(mode):
        global CAMERA_MODE
        if mode in ("record", "stream"):
            CAMERA_MODE = mode
            print(f"[WEB] Camera mode set to: {CAMERA_MODE}")
        return redirect(url_for("index"))

    @app.route("/livestream")
    def livestream():
        if not HAS_OPENCV:
            return "OpenCV (python3-opencv) not installed on Pi.", 500
        if CAMERA_MODE != "stream":
            return "Camera is in RECORD mode. Switch to STREAM mode on dashboard.", 403
        return Response(
            gen_frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    def start_dashboard():
        # accessible at http://<pi-ip>:5000/
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
else:
    def start_dashboard():
        print("Flask not installed; web dashboard disabled.")


# ---------- MAIN ----------
def main():
    global KILL_REQUESTED

    os.makedirs(DATA_DIR, exist_ok=True)

    # start dashboard in background thread
    dash_thread = threading.Thread(target=start_dashboard, daemon=True)
    dash_thread.start()

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    print("PIR + USB Arducam (FFmpeg) armed.")
    print(f"Saving all data → {DATA_DIR}")
    print("Web dashboard (if Flask installed) → http://<pi-ip>:5000/")
    time.sleep(2)

    GPIO.add_event_detect(PIR_PIN, GPIO.RISING, bouncetime=200)
    GPIO.add_event_callback(PIR_PIN, on_motion)

    try:
        while True:
            if KILL_REQUESTED:
                print("Kill switch activated from web dashboard. Shutting down...")
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    main()
