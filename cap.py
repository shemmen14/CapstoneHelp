# Program to run Pi motion sensor and operate camera

import os, time, threading, subprocess, shlex, shutil
from datetime import datetime
import RPi.GPIO as GPIO

# ---------- SETTINGS ----------
PIR_PIN = 17                          # BCM pin for PIR OUT
VIDEO_DIR = os.path.expanduser("~/videos")
RECORD_SECONDS = 5                    # clip length
COOLDOWN_SECONDS = 30                 # min time between triggers

DEVICE = "/dev/video0"                # your USB Arducam device
WIDTH, HEIGHT, FPS = 1920, 1080, 30       
INPUT_FORMAT = "mjpeg"              
ENCODER = "h264_v4l2m2m"              # try HW encoder; fallback to libx264 automatically
BITRATE = "6M"

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
    # Prefer HW encoder, else fallback to libx264
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

def on_motion(_ch):
    global last_trigger
    now = time.monotonic()
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
