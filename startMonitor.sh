#!/bin/bash
#this file is for helping daemonize the tracker with the use of cron
#add the following line to cron to make this script run at startup
#* * * * * /usr/bin/flock -n /tmp/fcj.lockfile -c /opt/GPSTrackerClient/startClient.sh --minutely

/usr/bin/python /opt/cubietruckStatus/monitor.py
