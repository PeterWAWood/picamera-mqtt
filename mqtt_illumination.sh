#!/bin/bash
DIRNAME="/home/pac/hand-hygiene/intervention/"
PIDFILE="/var/run/mqtt_illumination.pid"
STARTWAIT=5

cd "${DIRNAME}"
/usr/bin/python3 -m intervention_client.mqtt_illumination > "${DIRNAME}/startup.log" &
PID=$!
echo $PID > "${PIDFILE}"