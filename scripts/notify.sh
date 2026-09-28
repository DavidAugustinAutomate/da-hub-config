#!/bin/bash
# Zentrales Melde-Skript
# Aufruf: notify.sh "<titel>" "<nachricht>" "<prioritaet: low|default|high|urgent>"
#
# Aenderung 09.09.2026: Der Versand wird jetzt geprueft. Vorher ging die
# Ausgabe nach /dev/null -- ein fehlgeschlagener Versand blieb unbemerkt,
# die Ueberwachung war damit selbst unueberwacht.

TITEL="$1"
NACHRICHT="$2"
PRIO="${3:-default}"

NTFY_URL="http://127.0.0.1:9092/dahub-alerts"
LOGDATEI="/home/david/.local/state/dahub-notify.log"

mkdir -p "$(dirname "$LOGDATEI")"

ZEIT=$(date '+%Y-%m-%d %H:%M:%S')

CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  --max-time 15 \
  -H "Title: ${TITEL}" \
  -H "Priority: ${PRIO}" \
  -d "${NACHRICHT}" \
  "${NTFY_URL}" 2>/dev/null)

if [ "$CODE" = "200" ]; then
    echo "${ZEIT} OK   [${PRIO}] ${TITEL}: ${NACHRICHT}" >> "$LOGDATEI"
    exit 0
fi

# Fehlgeschlagen: ins Protokoll UND ins Systemjournal, damit es auffindbar
# bleibt, auch wenn niemand die Protokolldatei liest.
echo "${ZEIT} FEHL [${PRIO}] HTTP ${CODE} -- ${TITEL}: ${NACHRICHT}" >> "$LOGDATEI"
logger -t dahub-notify -p daemon.err \
  "Push fehlgeschlagen (HTTP ${CODE}): ${TITEL} -- ${NACHRICHT}"
exit 1
