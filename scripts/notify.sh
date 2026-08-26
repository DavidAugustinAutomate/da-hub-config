#!/bin/bash
# Zentrales Melde-Skript
# Aufruf: notify.sh "<titel>" "<nachricht>" "<prioritaet: low|default|high|urgent>"

TITEL="$1"
NACHRICHT="$2"
PRIO="${3:-default}"

NTFY_URL="https://da-hub.taile9dad7.ts.net:10000/dahub-alerts"

# Immer: Push senden
curl -s \
  -H "Title: ${TITEL}" \
  -H "Priority: ${PRIO}" \
  -d "${NACHRICHT}" \
  "${NTFY_URL}" > /dev/null

# Bei hoher/dringender Prioritaet zusaetzlich (Mail folgt in Teil 3)
