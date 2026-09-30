#!/bin/sh
# Builds the Mosquitto password file and starts the broker.
#   MQTT_API_PASSWORD   password of the backend service account "rakshak-api"
#   MQTT_DEVICE_USERS   "HUB-0001:pw,HUB-0002:pw" - one account per hub (username == hub id)
set -eu

DATA=/mosquitto/data
mkdir -p "$DATA"
PASSWD="$DATA/passwd"
: > "$PASSWD"

mosquitto_passwd -b "$PASSWD" rakshak-api "${MQTT_API_PASSWORD:?MQTT_API_PASSWORD must be set}"

IFS=','
for pair in ${MQTT_DEVICE_USERS:-}; do
    user=${pair%%:*}
    pass=${pair#*:}
    mosquitto_passwd -b "$PASSWD" "$user" "$pass"
done
unset IFS

chown mosquitto:mosquitto "$PASSWD" 2>/dev/null || true
chmod 0700 "$PASSWD"
exec mosquitto -c /mosquitto/config/mosquitto.conf
