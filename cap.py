# Program to operate camera and motion sensor for Raspberry pi 
# -Sam Hemmen

import os, time, threading, subprocess, shlex, shutil
from datetime import datetime
import RPi.GPIO as GPIO
import csv   # --- NEW ---

# --- NEW: plotting imports (safe if matplotlib missing) ---
try:
    import matplotlib
    matplotlib.use("Agg")  # non-GUI backend
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:
    HAS_MPL = False

# ---------- SETTINGS ----------
PIR_PIN = 17                          # BCM pin for PIR OUT
VIDEO_DIR = os.path.expanduser("~/videos")
RECORD_SECONDS = 5                    # clip length
COOLDOWN_SECONDS = 30                 # min time between triggers

DEVICE = "/dev/video0"                # USB Arducam device
WIDTH, HEIGHT, FPS = 1920, 1080, 30      
INPUT_FORMAT = "mjpeg"               
ENCODER = "h264_v4l2m2m"              # try HW encoder; fallback to libx264 automatically
BITRATE = "6M"

# ---------- NEW ----------
LOG_FILE = os.path.join(VIDEO_DIR, "motion_log.csv")

# ---------- STATE ----------
last_trigger = 0.0
record_lock = threading.Lock()

def run_cmd(cmd):
    return subprocess.run(
        shlex.split(cmd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

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
        
        cmd = base + f'-c:v {ENCODER} -b:v {BITRATE} {shlex.quote(outpath)}'
        test = run_cmd(cmd)
        if test.returncode == 0:
            return cmd  
        
        return base + f'-c:v libx264 -preset veryfast -crf 23 {shlex.quote(outpath)}'
    else:
        raise RuntimeError("ffmpeg not found")

def record_clip():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(VIDEO_DIR, f"motion_{ts}.mp4")
    print(f"[{ts}] Recording {RECORD_SECONDS}s -> {out}")

    cmd = ffmpeg_cmd(out)
    res = run_cmd(cmd)
    if res.returncode != 0:
        print("FFmpeg error:\n", res.stderr.strip() or res.stdout.strip())
    else:
        print(f"[{ts}] Saved {out}")

# -------- NEW: chart generation from CSV --------
def update_interval_chart():
    """Read motion_log.csv and generate a PNG chart of intervals between motions."""
    if not HAS_MPL:
        return
    if not os.path.exists(LOG_FILE):
        return

    indices = []
    deltas = []

    try:
        with open(LOG_FILE, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                delta_str = row.get("seconds_since_last_motion")
                if not delta_str or delta_str == "None":
                    continue
                try:
                    delta_val = float(delta_str)
                except ValueError:
                    continue
                deltas.append(delta_val)
                indices.append(len(deltas))
    except Exception:
        # Don't let plotting errors break main functionality
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

    out_png = os.path.join(VIDEO_DIR, "motion_intervals.png")
    try:
        plt.savefig(out_png)
    finally:
        plt.close()

# -------- NEW: CSV LOGGING FUNCTION --------
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

    # After successfully logging, update the PNG chart
    update_interval_chart()

def on_motion(_ch):
    global last_trigger
    now = time.monotonic()

    # calculate delta BEFORE cooldown early-return
    if last_trigger == 0.0:
        delta = None  # first detection
    else:
        delta = round(now - last_trigger, 3)

    # CSV log every detection (even if within cooldown)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_motion(timestamp, delta)

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

def main():
    os.makedirs(VIDEO_DIR, exist_ok=True)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    print("PIR + USB Arducam (FFmpeg) armed.")
    print(f"Clips → {VIDEO_DIR}")
    print(f"Motion log → {LOG_FILE}")
    time.sleep(2)

    GPIO.add_event_detect(PIR_PIN, GPIO.RISING, bouncetime=200)
    GPIO.add_event_callback(PIR_PIN, on_motion)

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()
