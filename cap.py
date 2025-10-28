#!/usr/bin/env python3
import os, time, threading, subprocess, shlex
from datetime import datetime
import RPi.GPIO as GPIO

# --- SETTINGS ---
PIR_PIN = 17
VIDEO_DIR = os.path.expanduser("~/videos")
RECORD_SECONDS = 5
COOLDOWN_SECONDS = 30
WIDTH, HEIGHT, FPS = 1920, 1080, 30

last_trigger_time = 0.0
recording_lock = threading.Lock()

def sh(cmd):
    # run a shell command and return (rc, stdout, stderr)
    p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err

def record_clip():
    """Record with libcamera-vid for RECORD_SECONDS, convert to MP4, clean up .h264"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(VIDEO_DIR, f"motion_{ts}.h264")
    mp4_path = os.path.join(VIDEO_DIR, f"motion_{ts}.mp4")

    print(f"[{ts}] Recording {RECORD_SECONDS}s video -> {raw_path}")

    # --inline: put SPS/PPS at keyframes so the file is easy to remux
    # -t in ms, --framerate, --width/--height for consistency
    cmd = (
        f"libcamera-vid -t {RECORD_SECONDS*1000} "
        f"--width {WIDTH} --height {HEIGHT} --framerate {FPS} "
        f"--codec h264 --inline -n -o {shlex.quote(raw_path)}"
    )
    rc, out, err = sh(cmd)
    if rc != 0:
        print("libcamera-vid failed:", err.strip() or out.strip())
        return

    # Prefer MP4Box (fast, no re-encode). Fallback to ffmpeg if MP4Box not available.
    if shutil.which("MP4Box"):
        rc, out, err = sh(f"MP4Box -add {shlex.quote(raw_path)} {shlex.quote(mp4_path)}")
        if rc != 0:
            print("MP4Box error:", err.strip() or out.strip())
            # try ffmpeg fallback
            rc, out, err = sh(f"ffmpeg -y -r {FPS} -i {shlex.quote(raw_path)} -c copy {shlex.quote(mp4_path)}")
            if rc != 0:
                print("ffmpeg error:", err.strip() or out.strip())
                print("Leaving raw .h264 file.")
                return
    else:
        # ffmpeg fallback
        rc, out, err = sh(f"ffmpeg -y -r {FPS} -i {shlex.quote(raw_path)} -c copy {shlex.quote(mp4_path)}")
        if rc != 0:
            print("ffmpeg error:", err.strip() or out.strip())
            print("Leaving raw .h264 file.")
            return

    # remove raw stream after successful mux
    try:
        os.remove(raw_path)
    except OSError:
        pass

    print(f"[{ts}] Saved {mp4_path}")

def on_motion_detected(channel):
    global last_trigger_time
    now = time.monotonic()

    if (now - last_trigger_time) < COOLDOWN_SECONDS:
        return
    last_trigger_time = now

    def worker():
        with recording_lock:
            try:
                record_clip()
            except Exception as e:
                print("Error during recording:", e)

    threading.Thread(target=worker, daemon=True).start()

def main():
    os.makedirs(VIDEO_DIR, exist_ok=True)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    print("PIR + Arducam (libcamera-vid) armed.")
    print(f"Clips will save to: {VIDEO_DIR}")
    time.sleep(2)

    GPIO.add_event_detect(PIR_PIN, GPIO.RISING, bouncetime=200)
    GPIO.add_event_callback(PIR_PIN, on_motion_detected)

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    import shutil
    main()
