# Program to operate camera and motion sensor for Raspberry pi 
# -Sam Hemmen

import os, time, threading, subprocess, shlex, shutil
from datetime import datetime
import RPi.GPIO as GPIO
import csv
import logging 

# --- plotting imports (non-GUI backend) ---
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:
    HAS_MPL = False

# --- web dashboard imports ---
try:
    from flask import Flask, send_from_directory, jsonify, render_template_string
    HAS_FLASK = True
except Exception:
    HAS_FLASK = False
    
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# ---------- PATHS / DATA DIR ----------
DATA_DIR = os.path.expanduser("~/CapstoneData")
LOG_FILE = os.path.join(DATA_DIR, "motion_log.csv")
GRAPH_FILE = os.path.join(DATA_DIR, "motion_intervals.png")

# ---------- GOOGLE DRIVE UPLOAD (rclone) ----------
GOOGLE_DRIVE_REMOTE = "gdrive:CapstoneData"  # rclone remote:path
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

KILL_REQUESTED = False                # <-- for web kill switch


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


# ---------- FFMPEG ----------
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
    global last_trigger, last_motion_timestamp, last_motion_delta, motion_event_count

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
    if delta is None:
        print(f"[{timestamp_str}] Motion detected (first event).")
    else:
        print(f"[{timestamp_str}] Motion detected. Δt since last motion = {delta} s.")

    # log every detection
    log_motion(timestamp_str, delta)

    # cooldown check for recording
    if (now - last_trigger) < COOLDOWN_SECONDS:
        return
    last_trigger = now

    def worker():
        with record_lock:
            try:
                record_clip()
            except Exception as e:
                print("Recording error:", e)

    threading.Thread(target=worker, daemon=True).start()


# ---------- WEB DASHBOARD ----------
app = Flask(__name__) if HAS_FLASK else None

DASHBOARD_TEMPLATE = """
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Capstone Motion Dashboard</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body { font-family: sans-serif; margin: 20px; }
        .card { border: 1px solid #ccc; border-radius: 8px; padding: 16px; max-width: 600px; }
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
    </style>
</head>
<body>
    <div class="card">
        <h1>Capstone Motion Dashboard</h1>
        <dl>
            <dt>Last motion timestamp</dt>
            <dd>{{ last_motion_timestamp or "No motion yet" }}</dd>

            <dt>Seconds since previous motion</dt>
            <dd>
                {% if last_motion_delta is none %}
                    N/A
                {% else %}
                    {{ last_motion_delta }} s
                {% endif %}
            </dd>

            <dt>Total motion events (since script start)</dt>
            <dd>{{ motion_event_count }}</dd>
        </dl>

        <h2>Intervals Between Motions</h2>
        {% if graph_exists %}
            <img src="/graph" alt="Motion intervals graph">
        {% else %}
            <p>No interval graph yet. It will appear after a few motion events.</p>
        {% endif %}

        <h2>Controls</h2>
        <form action="/kill" method="get">
            <button class="kill">STOP PROGRAM</button>
        </form>
    </div>
</body>
</html>
"""

if HAS_FLASK:
    @app.route("/")
    def index():
        return render_template_string(
            DASHBOARD_TEMPLATE,
            last_motion_timestamp=last_motion_timestamp,
            last_motion_delta=last_motion_delta,
            motion_event_count=motion_event_count,
            graph_exists=os.path.exists(GRAPH_FILE),
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
        )

    @app.route("/kill")
    def kill():
        global KILL_REQUESTED
        KILL_REQUESTED = True
        return "<h1>Kill signal sent. Program will shut down.</h1>", 200

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
