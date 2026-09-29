#!/usr/bin/env bash
# notify-stdin.sh – Meldung von Claude Code an David.
# Text NUR von der Standardeingabe, fester Titel, keine Argumente.
# Der Text wird nie als Befehl ausgewertet: kein eval, keine Expansion,
# er landet nur als Datenwert bei notify.sh (curl --data-raw).
set -euo pipefail
export LC_ALL=C.utf8
[ $# -eq 0 ] || { echo "notify-stdin.sh: keine Argumente erlaubt" >&2; exit 2; }
roh=$(head -c 4000)                                   # Eingabe begrenzen
text=$(printf '%s' "$roh" | tr '\n\t' '  ' | tr -d '\000-\010\013-\037\177')   # Steuerzeichen weg
text=${text:0:500}                                    # hoechstens 500 Zeichen (nicht Bytes)
[ -n "${text// /}" ] || { echo "notify-stdin.sh: leerer Text" >&2; exit 1; }
exec /home/david/scripts/notify.sh "da-hub: Claude Code" "$text" default
