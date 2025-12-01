
Capstone Motion Detection System - Fresh Raspberry Pi Setup Instructions
=====================================================================

This document explains how to set up the complete Capstone Motion System
on a FRESH Raspberry Pi — including motion detection, video recording,
Google Drive uploading, CSV logging, graphing, and the live web dashboard.
Follow these steps in order. Yes, to answer your suspicions, it looks nice because I had Chat format it for me.

------------------------------------------------------------
1. INITIAL RASPBERRY PI SETUP
------------------------------------------------------------
• Boot a fresh Raspberry Pi 5
• Connect to a personal phone hotspot
• Update system packages:

    sudo apt update
    sudo apt upgrade -y

• Set your Wi-Fi country so wireless works properly:

    sudo raspi-config
    → Localisation Options or System Options
    → WLAN Country
    → Select US
    → Finish and reboot

------------------------------------------------------------
2. INSTALL REQUIRED PACKAGES
------------------------------------------------------------
Install all packages used by the Capstone Motion Detection System.

### Core system packages
    sudo apt install -y python3-pip python3-flask python3-matplotlib ffmpeg rclone git

### GPIO + PIR sensor packages
    sudo apt install -y python3-rpi.gpio python3-lgpio libgpiod2

### USB Camera (Arducam / UVC) packages
    sudo apt install -y v4l-utils

### Optional but recommended
    sudo apt install -y python3-numpy python3-requests htop neofetch

Verify installations:

    python3 -c "import RPi.GPIO, flask, matplotlib"

------------------------------------------------------------
3. SET UP GOOGLE DRIVE UPLOADS (rclone)
------------------------------------------------------------
Configure rclone so the Pi can upload videos, CSV, and graphs
to a Google Drive folder automatically.

Run:

    rclone config

Then:
    n    (new remote)
    gdrive   ← name MUST be exactly this
    13       (Google Drive)
    Press Enter for Client ID/Secret
    Select: Full access
    Press Enter for root folder
    Auto-config: YES (if Pi has a browser)
       OR
    Auto-config: NO → open the provided URL on your laptop → paste code back into Pi

After completion, test:

    rclone ls gdrive:

Create a Drive folder:

    rclone mkdir gdrive:CapstoneData

------------------------------------------------------------
4. CREATE PROJECT FOLDER
------------------------------------------------------------

    mkdir ~/CapstoneHelp
    mkdir ~/CapstoneData

Copy your cap.py script into:

    ~/CapstoneHelp/cap.py

------------------------------------------------------------
5. RUN THE PROGRAM
------------------------------------------------------------

Navigate to the project folder:

    cd ~/CapstoneHelp

Run:

    python3 cap.py

If everything is correct, terminal will show:
    PIR + USB Arducam armed…
    Saving data → /home/pi/CapstoneData
    Dashboard → http://<pi-ip>:5000/

------------------------------------------------------------
6. ACCESS THE WEB DASHBOARD
------------------------------------------------------------
First, find your Raspberry Pi’s IP address:

    hostname -I

Example output:

    192.168.8.24

On a device connected to the **same network** (phone, laptop):

Open:

    http://<pi-ip>:5000/

Example:

    http://192.168.8.24:5000/

Dashboard shows:
    • Last motion time
    • Seconds since previous motion
    • Graph of intervals
    • STOP PROGRAM button

NOTE:
If you're on MSU Secure or Guest networks, these isolate devices.
I recommend using your phone hotspot instead.

------------------------------------------------------------
7. STOP THE PROGRAM
------------------------------------------------------------
You have 3 ways to stop the program:

1) From the web dashboard:
    Press the STOP PROGRAM button.

2) From the terminal:
    Press CTRL + C

3) Using the stopcap alias (recommended):
Add this to ~/.bashrc:

    alias stopcap='sudo pkill -f cap.py; sudo pkill -f python3; sudo raspi-gpio set 17 ip; echo "Capstone program stopped and GPIO reset."'

Activate:

    source ~/.bashrc

Run anytime:

    stopcap

------------------------------------------------------------
8. AUTOSTART ON BOOT (OPTIONAL)
------------------------------------------------------------
If you want the program to run automatically at boot,
create a systemd service:

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

Enable and start:

    sudo systemctl enable capstone
    sudo systemctl start capstone

------------------------------------------------------------
9. FILE LOCATIONS
------------------------------------------------------------
All generated data is stored in:

    /home/pi/CapstoneData/

Files include:
    • motion_YYYYMMDD_HHMMSS.mp4
    • motion_log.csv
    • motion_intervals.png
    • Uploads synced automatically to Google Drive

------------------------------------------------------------
10. TROUBLESHOOTING
------------------------------------------------------------

• GPIO busy error:
    sudo pkill -f cap.py
    sudo pkill -f python3
    sudo raspi-gpio set 17 ip

• Dashboard cannot load:
    - Ensure Pi and laptop are on SAME network
    - Ensure program is running
    - Try: curl http://<pi-ip>:5000

• Wi-Fi blocked (rfkill):
    sudo raspi-config → WLAN Country

• USB camera not detected:
    v4l2-ctl --list-devices
    v4l2-ctl --list-formats-ext -d /dev/video0

------------------------------------------------------------
THE END
------------------------------------------------------------
