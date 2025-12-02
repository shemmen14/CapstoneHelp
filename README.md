
Capstone Motion Detection System - Fresh Raspberry Pi Setup Instructions
=====================================================================

This document explains how to set up the complete Capstone Motion System
on a FRESH Raspberry Pi — including motion detection, RECORD vs STREAM camera modes,
video recording, Google Drive uploading, CSV logging, graphing, and the live web dashboard
with a continuous livestream that DOES NOT break during page updates.

Yes, to confirm your suspicions, this was indeed formatted by Mr. GPT.

Follow these steps in order.

------------------------------------------------------------
1. INITIAL RASPBERRY PI SETUP
------------------------------------------------------------
• Boot a fresh Raspberry Pi 5  
• Connect to a personal phone hotspot  
• Update system packages:

    sudo apt update
    sudo apt upgrade -y

• Set Wi-Fi country:

    sudo raspi-config
      → System Options
      → WLAN Country
      → Select US
      → Finish and reboot

------------------------------------------------------------
2. INSTALL REQUIRED PACKAGES
------------------------------------------------------------

### Core system packages
    sudo apt install -y python3-pip python3-flask python3-matplotlib ffmpeg rclone git

### GPIO + PIR sensor packages
    sudo apt install -y python3-rpi.gpio python3-lgpio libgpiod2

### USB Camera (Arducam / UVC) packages
    sudo apt install -y v4l-utils

### OpenCV for livestreaming
    sudo apt install -y python3-opencv

### Optional but recommended
    sudo apt install -y python3-numpy python3-requests htop neofetch

### Verify core packages
    python3 -c "import RPi.GPIO, flask, matplotlib, cv2"

------------------------------------------------------------
3. SET UP GOOGLE DRIVE UPLOADS (rclone)
------------------------------------------------------------

    rclone config

Steps:
    n            (new remote)
    gdrive       (name EXACTLY: gdrive)
    13           (Google Drive)
    Enter through Client ID/Secret
    Choose: Full access
    Auto-config: YES (or NO and paste URL token)
    Confirm remote

Test:
    rclone ls gdrive:

Create cloud storage folder:
    rclone mkdir gdrive:CapstoneData

------------------------------------------------------------
4. CREATE PROJECT FOLDERS
------------------------------------------------------------

    mkdir ~/CapstoneHelp
    mkdir ~/CapstoneData

Place your cap.py script in:

    ~/CapstoneHelp/cap.py

------------------------------------------------------------
5. RUN THE PROGRAM
------------------------------------------------------------

    cd ~/CapstoneHelp
    python3 cap.py

Expected output:
    PIR + USB Arducam armed…
    Saving all data → /home/pi/CapstoneData
    Web dashboard → http://<pi-ip>:5000/

------------------------------------------------------------
6. ACCESS THE WEB DASHBOARD
------------------------------------------------------------

Find your IP:

    hostname -I

Example:  
    192.168.8.24

Visit from phone/laptop on same hotspot:

    http://192.168.8.24:5000/

Dashboard includes:
    • RECORD / STREAM mode switch  
    • Continuous livestream in STREAM mode  
    • Motion timestamps  
    • Seconds since previous motion  
    • Motion event count  
    • Auto-updating interval graph  
    • STOP PROGRAM kill switch  

IMPORTANT:  
MSU Guest / Secure network **isolates devices** → use phone hotspot.

------------------------------------------------------------
7. CAMERA MODES (NEW & IMPORTANT)
------------------------------------------------------------

### RECORD Mode
- PIR triggers video recordings  
- Files saved to ~/CapstoneData  
- Uploads to Google Drive  
- **Livestream is OFF** (camera reserved for FFmpeg)

### STREAM Mode
- PIR still logs events  
- NO video recording  
- **Continuous livestream active** using OpenCV V4L2 backend  
- Never conflicts with recording  
- No page refresh interruptions (JS live updates)

Switch modes instantly from the web dashboard.

------------------------------------------------------------
8. STOP THE PROGRAM
------------------------------------------------------------

### Option 1: From Web Dashboard
Press **STOP PROGRAM** button.

### Option 2: Keyboard
Press:

    CTRL + C

### Option 3: stopcap alias (recommended)

Add to ~/.bashrc:

    alias stopcap='sudo pkill -f cap.py; sudo pkill -f python3; sudo raspi-gpio set 17 ip; echo "Capstone program stopped and GPIO reset."'

Activate:

    source ~/.bashrc

Run:

    stopcap

------------------------------------------------------------
9. AUTOSTART PROGRAM ON BOOT (OPTIONAL)
------------------------------------------------------------

    sudo nano /etc/systemd/system/capstone.service

Paste:

    [Unit]
    Description=Capstone Motion System
    After=network.target

    [Service]
    ExecStart=/usr/bin/python3 /home/pi/CapstoneHelp/cap.py
    WorkingDirectory=/home/pi/CapstoneHelp
    Restart=always
    User=pi

    [Install]
    WantedBy=multi-user.target

Enable autostart:

    sudo systemctl enable capstone
    sudo systemctl start capstone

------------------------------------------------------------
10. FILE LOCATIONS
------------------------------------------------------------

All generated files go to:

    /home/pi/CapstoneData/

Includes:
    • motion_YYYYMMDD_HHMMSS.mp4  
    • motion_log.csv  
    • motion_intervals.png  
    • all synced to Google Drive  

------------------------------------------------------------
11. TROUBLESHOOTING
------------------------------------------------------------

• GPIO busy error:
    sudo pkill -f cap.py
    sudo pkill -f python3
    sudo raspi-gpio set 17 ip

• Dashboard not loading:
    - Use hotspot (campus networks isolate devices)
    - Ensure cap.py is running
    - Try: curl http://<pi-ip>:5000

• Livestream flicker:
    ✔ FIXED — Removed HTML meta refresh  
    ✔ Added JavaScript to update stats without reloading  
    ✔ Stream uses V4L2 backend for stability  

• USB camera debugging:
    v4l2-ctl --list-devices
    v4l2-ctl --list-formats-ext -d /dev/video0

• Google Drive upload errors:
    rclone ls gdrive:
    rclone mkdir gdrive:CapstoneData

------------------------------------------------------------
THE END
------------------------------------------------------------
