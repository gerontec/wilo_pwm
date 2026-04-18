#!/bin/bash
# deploy.sh — Dateien auf Pico W hochladen und per MQTT resetten
#
# Verwendung:
#   ./deploy.sh           → alle Dateien deployen + reset
#   ./deploy.sh main.py   → nur eine Datei + reset
#   ./deploy.sh --no-reset → nur hochladen, kein reset

PICO_IP="192.168.178.167"
WEBREPL_PW="7291"
MQTT_HOST="192.168.178.218"
MQTT_RESET_TOPIC="heatp/pump"
MQTT_STATUS_TOPIC="heatp/pins"
WEBREPL="python3 /home/gh/webrepl_cli.py -p $WEBREPL_PW"

NO_RESET=0
FILES=()

for arg in "$@"; do
    if [ "$arg" = "--no-reset" ]; then
        NO_RESET=1
    else
        FILES+=("$arg")
    fi
done

# Standard: alle Pico-Dateien
if [ ${#FILES[@]} -eq 0 ]; then
    FILES=(
        main.py
        pwmfeedback_pio.py
        pwmfeedback_core1.py
    )
fi

echo "=== Deploy zu $PICO_IP ==="
for f in "${FILES[@]}"; do
    REMOTE=$(basename "$f")
    echo "  → $f"
    $WEBREPL "$f" "$PICO_IP:$REMOTE" 2>&1 | grep -E "Sent|Error|error"
done

if [ $NO_RESET -eq 0 ]; then
    echo "=== Warte auf MQTT-Verbindung des Pico ==="
    timeout 20 mosquitto_sub -h $MQTT_HOST -t heatp/log -C 1 --quiet | grep -q "Start" || true
    echo "=== Reset via MQTT ==="
    mosquitto_pub -h $MQTT_HOST -t $MQTT_RESET_TOPIC -m "reset"
    echo "  Reset gesendet, warte 13s..."
    sleep 13
    echo "=== Status nach Reset ==="
    mosquitto_sub -h $MQTT_HOST -t $MQTT_STATUS_TOPIC -C 1 \
        | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  FW:      {d[\"FW\"]}')
print(f'  UPTIME:  {d[\"UPTIME\"]}s')
print(f'  PWM_MIN: {d[\"PWM_MIN\"]}')
print(f'  Duty:    {d[\"PumpDuty\"]}%')
print(f'  Status:  {d[\"PumpStatus\"]}')
"
fi
