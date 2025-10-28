#!/usr/bin/env python3
import os
import time
import threading
from datetime import datetime
import RPi.GPIO as GPIO

# Picamera2 import
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

# --- SETTINGS ---
PIR_PIN = 17              # BCM GPIO for PIR
VIDEO_DIR = os.path.expanduser("~/videos")
RECORD_SECONDS = 5        # Length of each clip
COOLDOWN_SECONDS = 30     # Minimum time between triggers

# --- STATE ---
last_trigger_time = 0.0
recording_lock = threading.Lock()

# --- Camera setup ---
picam2 = Picamera2()
# 1080p@30 is a good default; adjust if needed
video_config = picam2.create_video_configuration(main={"size": (1920, 1080), "format": "XBGR8888"})
picam2.configure(video_config)

# H.264 encoder at ~10 Mbps (adjust if needed)
encoder = H264Encoder(bitrate=10_000_000)

# Start the camera so it’s ready to record instantly
picam2.start()

def record_clip():
    """Record a 5-second MP4 clip to VIDEO_DIR with a timestamped name."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(VIDEO_DIR, f"motion_{ts}.mp4")

    # MP4 container via FFmpegOutput (hardware encode -> H.264 -> MP4)
    output = FfmpegOutput(outfile)

    print(f"[{ts}] Recording {RECORD_SECONDS}s video -> {outfile}")
    picam2.start_recording(encoder, output)
    time.sleep(RECORD_SECONDS)
    picam2.stop_recording()
    print(f"[{ts}] Saved {outfile}")

def on_motion_detected(channel):
    global last_trigger_time
    now = time.monotonic()

    # Cooldown check
    if (now - last_trigger_time) < COOLDOWN_SECONDS:
        # Still cooling down; ignore
        return

    # Atomically set the trigger time, then record in a thread
    last_trigger_time = now

    def do_record():
        # Prevent overlapping recordings if GPIO bounces
        with recording_lock:
            try:
                record_clip()
            except Exception as e:
                print(f"Error during recording: {e}")

    threading.Thread(target=do_record, daemon=True).start()

def main():
    os.makedirs(VIDEO_DIR, exist_ok=True)

    # PIR setup
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    print("PIR+Arducam armed. Warm-up for ~30–60s if sensor is fresh-powered.")
    print(f"Clips will save to: {VIDEO_DIR}")
    time.sleep(2)  # short stabilization

    # Rising edge = motion detected
    GPIO.add_event_detect(PIR_PIN, GPIO.RISING, bouncetime=200)
    GPIO.add_event_callback(PIR_PIN, on_motion_detected)

    try:
        while True:
            time.sleep(0.2)  # keep main thread alive
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()
        picam2.stop()

if __name__ == "__main__":
    main()
