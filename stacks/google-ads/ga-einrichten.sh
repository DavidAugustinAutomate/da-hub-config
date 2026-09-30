#!/usr/bin/env bash
# Google Ads Etappe 1a: Dateien ablegen, venv mit google-ads==33.0.0, Tests. Kein Aufruf an Google Ads
# (pip laedt nur Pakete von PyPI). Quelle = Verzeichnis dieses Skripts (Repo stacks/google-ads/ oder ~/tmp/ga),
# Ziel = ~/stacks/google-ads. oauth-client.json und .env werden nicht angefasst.
# Aufruf: bash ~/da-hub-config/stacks/google-ads/ga-einrichten.sh
set -euo pipefail
Q=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); G=$HOME/stacks/google-ads
log() { echo "$(date +%T) $*"; }
umask 077
[ "$Q" = "$G" ] && { echo "Quelle und Ziel sind gleich ($G) – aus dem Repo oder ~/tmp/ga aufrufen"; exit 1; }

log "1 Dateien von $Q nach $G (600, Verzeichnis 700)"
mkdir -p "$G"; chmod 700 "$G"
for f in ads_common.py ads_auth.py ads_check.py test_ads.py requirements.txt env.vorlage README.md; do
  install -m 600 "$Q/$f" "$G/$f"
done
ls -la "$G" | awk 'NR>1 {print $1, $3, $5, $NF}'

log "2 venv"
[ -d "$G/venv" ] && log "venv besteht schon – wird weiterverwendet" || python3 -m venv "$G/venv"
"$G/venv/bin/python" --version
"$G/venv/bin/pip" install --quiet --disable-pip-version-check --require-virtualenv -r "$G/requirements.txt"
"$G/venv/bin/pip" freeze --disable-pip-version-check > "$G/requirements.lock.txt"; chmod 600 "$G/requirements.lock.txt"
echo "   google-ads $("$G/venv/bin/python" -c 'import importlib.metadata as m; print(m.version("google-ads"))'), Pakete im venv: $(grep -c . "$G/requirements.lock.txt")"
# grep: 0 = Treffer, 1 = kein Treffer (wird gemeldet), >1 = echter Fehler (Abbruch) – kein '|| true'
rc=0; treffer=$(grep -E '^(google-ads|google-auth|google-auth-oauthlib|grpcio|protobuf|proto-plus)==' "$G/requirements.lock.txt") || rc=$?
case "$rc" in
  0) sed 's/^/   /' <<<"$treffer" ;;
  1) echo "   WARNUNG: keines der Kernpakete in requirements.lock.txt gefunden" ;;
  *) echo "   FEHLER: grep rc=$rc beim Lesen von requirements.lock.txt"; exit 1 ;;
esac

log "3 py_compile + Mocktests (ohne Netz)"
cd "$G"
"$G/venv/bin/python" -m py_compile ads_common.py ads_auth.py ads_check.py test_ads.py && echo "   py_compile OK"
"$G/venv/bin/python" -m unittest test_ads 2>&1 | tail -n 4

log "4 Stand"
ls -la "$G" | awk 'NR>1 {print $1, $3, $5, $NF}'
[ -e "$G/.env" ] && echo "   .env vorhanden (Laenge der Werte: $(awk -F= '{print $1, length($2)}' "$G/.env" | paste -sd' '))" || echo "   .env noch nicht vorhanden (schreibt ads_auth.py)"
