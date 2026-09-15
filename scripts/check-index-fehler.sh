#!/bin/bash
# Meldet einmal taeglich neu und endgueltig gescheiterte Indexierungen per ntfy.
# Endgueltig = status 'failed' UND attempts >= MAX_ATTEMPTS (der Worker holt
# Jobs mit weniger Versuchen selbst zurueck, die sind hier bewusst nicht dabei).
# Jede Datei wird genau einmal gemeldet; die IDs stehen in der Zustandsdatei.

set -u

MAX_ATTEMPTS=3
STATE_DIR="$HOME/.local/state"
STATE="$STATE_DIR/dahub-index-fehler.ids"
NOTIFY="$HOME/scripts/notify.sh"
CONTAINER="postgres-vector"

mkdir -p "$STATE_DIR"
touch "$STATE"

if ! command -v docker >/dev/null 2>&1; then
    echo "docker nicht gefunden" >&2
    exit 1
fi

AKTUELL=$(docker exec "$CONTAINER" psql -U dahub -d knowledge -t -A -F'|' -c \
"SELECT id,
        regexp_replace(origin_path, '^.*/', ''),
        left(coalesce(last_error, 'ohne Meldung'), 60)
   FROM file_jobs
  WHERE status = 'failed' AND attempts >= ${MAX_ATTEMPTS}
  ORDER BY id;" 2>/dev/null)

if [ $? -ne 0 ]; then
    echo "Abfrage fehlgeschlagen" >&2
    exit 1
fi

AKTUELL=$(printf '%s\n' "$AKTUELL" | sed '/^$/d')
GESAMT=$(printf '%s\n' "$AKTUELL" | grep -c . || true)

if [ "$GESAMT" -eq 0 ]; then
    exit 0
fi

NEU=$(printf '%s\n' "$AKTUELL" | awk -F'|' 'NR==FNR { gesehen[$1]=1; next } !($1 in gesehen)' "$STATE" -)
ANZAHL=$(printf '%s\n' "$NEU" | grep -c . || true)

if [ "$ANZAHL" -eq 0 ]; then
    exit 0
fi

NAMEN=$(printf '%s\n' "$NEU" | awk -F'|' '{ print "- " $2 }' | head -3)
WEITERE=$((ANZAHL - 3))
if [ "$WEITERE" -gt 0 ]; then
    NAMEN="${NAMEN}
- ... und ${WEITERE} weitere"
fi

# Fehlertexte grob gruppieren: Zahlen raus, dann die drei haeufigsten
TYPEN=$(printf '%s\n' "$NEU" \
    | awk -F'|' '{ print $3 }' \
    | sed -E 's/[0-9]+/N/g' \
    | cut -c1-45 \
    | sort | uniq -c | sort -rn | head -3 \
    | awk '{ n=$1; $1=""; sub(/^ /,""); print "- " n "x " $0 }')

TEXT="${ANZAHL} neu, ${GESAMT} endgueltig gescheitert insgesamt.

${NAMEN}

${TYPEN}

Rueckholen: UPDATE file_jobs SET status='pending', attempts=0, last_error=NULL WHERE status='failed';"

if [ -x "$NOTIFY" ]; then
    "$NOTIFY" "Wissensbasis: ${ANZAHL} Dateien nicht indexiert" "$TEXT" default
    RC=$?
else
    echo "$NOTIFY nicht ausfuehrbar" >&2
    RC=1
fi

# IDs erst nach erfolgreicher Meldung merken, sonst morgen erneut versuchen
if [ "$RC" -eq 0 ]; then
    printf '%s\n' "$NEU" | awk -F'|' '{ print $1 }' >> "$STATE"
else
    exit 1
fi
