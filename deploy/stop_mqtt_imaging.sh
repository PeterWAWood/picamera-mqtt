#!/bin/bash
PIDFILE="/var/run/mqtt_imaging.pid"

if [ -f "${PIDFILE}" ]; then
	kill -SIGINT `cat "${PIDFILE}"` && sudo rm "${PIDFILE}"
fi
