#!/bin/bash

export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority

/usr/bin/python3 /home/pi/chatty-node/status_window.py
