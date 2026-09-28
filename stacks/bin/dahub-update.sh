#!/usr/bin/env bash
# dahub-update.sh – Updates der Docker-Dienste auf da-hub (Phase 2).
#
#   dahub-update.sh --pruefen [--gruppe auto|freigabe | --dienst NAME]   zeigt nur, was geschehen wuerde
#   dahub-update.sh --gruppe auto                                        aktualisiert alle faelligen Dienste der Gruppe
#   dahub-update.sh --dienst NAME [--version TAG]                        ein Dienst; --version fuer Freigabe/Major
#
# Laeuft als david (Gruppe docker). Werte aus .env-Dateien werden nie ausgegeben.
# Pause von Worker/Scan/Nextcloud-Cron ueber das Wartungsflag (feste Drop-ins dahub-wartung.conf).
set -euo pipefail
umask 077

BIN=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
CONF=$BIN/dienste.conf
NV=$BIN/neue-version.py
STATE=$HOME/.local/state
FLAG=$STATE/dahub-wartung
LOG=$STATE/dahub-update.log
LOCK=$STATE/dahub-update.lock
REPO=$HOME/da-hub-config
BACKUP=$HOME/backup
NOTIFY=$HOME/scripts/notify.sh
KARENZ=7
DUMPS_BEHALTEN=4
WORKER_MAX=4200                                   # max. Wartezeit auf einen laufenden Worker (s)
PAUSE_UNITS="wissensbasis-worker.service wissensbasis-scan.service nextcloud-cron.service"
WORKER_DIENSTE=" docling ollama libreoffice nextcloud nextcloud-db "
LITELLM_VERBOTEN=" 1.82.7 v1.82.7 1.82.8 v1.82.8 "
H=100.93.33.0
OLLAMA_REF=$HOME/stacks/tests/ollama-referenz.json
OLLAMA_SATZ="Der Mietvertrag fuer den Standort Zuerich wird per 31. Dezember gekuendigt."
OLLAMA_SCHWELLE=0.999

# ------------------------------------------------------------------ Argumente
modus=update; gruppe=""; dienst=""; version=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pruefen) modus=pruefen ;;
    --ollama-referenz) modus=referenz ;;
    --gruppe) gruppe=${2:?}; shift ;;
    --dienst) dienst=${2:?}; shift ;;
    --version) version=${2:?}; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1"; exit 2 ;;
  esac
  shift
done
[ "$modus" = referenz ] || [ -n "$gruppe" ] || [ -n "$dienst" ] || { echo "--gruppe oder --dienst angeben"; exit 2; }
[ -z "$version" ] || [ -n "$dienst" ] || { echo "--version nur zusammen mit --dienst"; exit 2; }

mkdir -p "$STATE"
tmp=$(mktemp -d)
log() { echo "$(date '+%F %T') $*"; }
melden() { "$NOTIFY" "$1" "$2" "${3:-default}" >/dev/null 2>&1 || log "WARNUNG: notify.sh fehlgeschlagen"; }

# ------------------------------------------------------------------ Dienstliste
declare -A DIR IMG LINIE GRUPPE TEST REPOF
REIHE=()
while read -r n d i l g t r; do
  [ -z "${n:-}" ] || [[ "$n" == \#* ]] && continue
  DIR[$n]=${d/#\~/$HOME}; IMG[$n]=$i; LINIE[$n]=$l; GRUPPE[$n]=$g; TEST[$n]=$t; REPOF[$n]=$r
  REIHE+=("$n")
done < "$CONF"

auswahl=()
for n in "${REIHE[@]}"; do
  if [ -n "$dienst" ]; then [ "$n" = "$dienst" ] && auswahl+=("$n")
  elif [ "${GRUPPE[$n]}" = "$gruppe" ]; then auswahl+=("$n"); fi
done
[ "$modus" = referenz ] || [ ${#auswahl[@]} -gt 0 ] || { echo "Kein Dienst gefunden (${dienst:-Gruppe $gruppe})"; exit 2; }

compose() { docker compose --project-directory "${DIR[$1]}" -f "${DIR[$1]}/docker-compose.yml" "${@:2}"; }
tag_in_datei() {  # aktueller Tag des Dienstes laut Compose-Datei (ohne Aufloesung von Werten)
  compose "$1" config --no-interpolate --format json | python3 -c '
import json, sys
img = json.load(sys.stdin)["services"][sys.argv[1]]["image"]
print(img.rsplit(":", 1)[1] if ":" in img.split("/")[-1] else "latest")' "$1"
}

# ------------------------------------------------------------------ Tests (0 = gruen)
occ() { docker exec -u www-data nextcloud php occ "$@"; }
envwert() {  # Wert aus einer env-Datei, nie ausgeben
  local w; w=$(sed -n -E "s/^(export[[:space:]]+)?$2=//p" "$1" | head -1)
  w=${w#\"}; w=${w%\"}; w=${w#\'}; w=${w%\'}; printf '%s' "$w"
}
hostport() {  # Adresse eines veroeffentlichten Ports; 0.0.0.0 -> 127.0.0.1
  local b; b=$(docker port "$1" "$2" 2>/dev/null | head -1); [ -n "$b" ] || return 1
  local hip=${b%:*}; case "$hip" in 0.0.0.0|"[::]") hip=127.0.0.1 ;; esac
  echo "$hip:${b##*:}"
}
t_gotenberg() {
  curl -sf -m 5 "http://127.0.0.1:3000/health" >/dev/null || return 1
  printf '<html><body><h1>dahub-update</h1></body></html>' > "$tmp/index.html"
  local c; c=$(curl -s -m 60 -o "$tmp/g.pdf" -w '%{http_code}' -F "files=@$tmp/index.html" http://127.0.0.1:3000/forms/chromium/convert/html)
  [ "$c" = 200 ] && [ "$(head -c 5 "$tmp/g.pdf")" = "%PDF-" ]
}
t_ntfy() {
  local base topic msg sub pid
  base="http://$(hostport ntfy 80/tcp)" || return 1
  curl -sf -m 5 "$base/v1/health" >/dev/null || return 1
  topic="dahub-selbsttest-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"; msg="update-$(date +%s)"; sub=$tmp/ntfy.json
  curl -sN -m 12 "$base/$topic/json" > "$sub" & pid=$!
  sleep 2
  curl -sf -m 10 -d "$msg" "$base/$topic" >/dev/null || { kill "$pid" 2>/dev/null; return 1; }
  wait "$pid" || true
  grep -q "\"message\":\"$msg\"" "$sub"
}
t_docling() {
  curl -sf -m 5 "http://$H:5001/health" >/dev/null || return 1
  curl -s -m 600 -F "files=@$HOME/stacks/tests/test.pdf" "http://$H:5001/v1/convert/file" -o "$tmp/d.json" || return 1
  grep -q 'Dahubtest4711' "$tmp/d.json"
}
ollama_embed() {  # fester Testsatz -> $1 (JSON der Ollama-API)
  curl -s -m 180 "http://$H:11434/api/embed" \
    -d "{\"model\":\"bge-m3\",\"input\":\"$OLLAMA_SATZ\"}" -o "$1"
}
t_ollama() {  # Laenge 1024 und Kosinus-Aehnlichkeit zur gespeicherten Referenz >= OLLAMA_SCHWELLE
  [ -f "$OLLAMA_REF" ] || { log "t_ollama: Referenz fehlt ($OLLAMA_REF) – zuerst --ollama-referenz"; return 1; }
  ollama_embed "$tmp/e.json" || return 1
  python3 - "$tmp/e.json" "$OLLAMA_REF" "$OLLAMA_SCHWELLE" <<'PY'
import json, math, sys
try:
    v = json.load(open(sys.argv[1]))["embeddings"][0]
    r = json.load(open(sys.argv[2]))["vektor"]
except (ValueError, KeyError, IndexError, TypeError):
    sys.exit(1)
if len(v) != 1024 or len(r) != 1024:
    print(f"  t_ollama: Laenge {len(v)} (Referenz {len(r)})", file=sys.stderr); sys.exit(1)
cos = sum(a * b for a, b in zip(v, r)) / (math.sqrt(sum(a * a for a in v)) * math.sqrt(sum(b * b for b in r)))
print(f"  t_ollama: Kosinus zur Referenz {cos:.6f} (Schwelle {sys.argv[3]})", file=sys.stderr)
sys.exit(0 if cos >= float(sys.argv[3]) else 1)
PY
}
t_libreoffice() {
  printf 'Dahubtest4711\n' > "$tmp/lo.txt"; rm -f "$tmp/lo.pdf"
  curl -s -m 120 -F "file=@$tmp/lo.txt" -F "convert-to=pdf" "http://$H:2004/request" -o "$tmp/lo.pdf" || return 1
  [ "$(head -c 5 "$tmp/lo.pdf" 2>/dev/null)" = "%PDF-" ]
}
t_nextcloud() {  # erwartete Version aus der Compose-Datei; WebDAV mit den Zugangsdaten des Scanners
  local soll unit=/etc/systemd/system/wissensbasis-scan.service url urlvar var pw code j
  soll=$(tag_in_datei nextcloud)
  occ status --output=json 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
sys.exit(0 if d.get("installed") and not d.get("maintenance") and not d.get("needsDbUpgrade") and d.get("versionstring") == sys.argv[1] else 1)' "$soll" || return 1
  url=$(grep -oE -- '--nextcloud-url[= ]+[^ ]+' "$unit" | head -1 | sed -E 's/^--nextcloud-url[= ]+//; s/^"//; s/"$//')
  if [[ "$url" =~ ^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$ ]]; then url=$(envwert "$HOME/.dahub-env" "${BASH_REMATCH[1]}"); fi
  url=${url%/}
  var=$(grep -oE -- '--nextcloud-password[= ]+"?\$\{?[A-Za-z_][A-Za-z0-9_]*' "$unit" | head -1 | grep -oE '[A-Za-z_][A-Za-z0-9_]*$')
  pw=$(envwert "$HOME/.dahub-env" "$var"); [ -n "$pw" ] || return 1
  urlvar=${url#*://}; urlvar=${urlvar%%/*}
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 -X PROPFIND -H 'Depth: 0' \
    --netrc-file <(printf 'machine %s login wissensbasis-bot password %s\n' "${urlvar%%:*}" "$pw") \
    "$url/remote.php/dav/files/wissensbasis-bot/")
  [ "$code" = 207 ] || return 1
  j=$(curl -s -m 20 "https://da-hub.taile9dad7.ts.net/status.php") || return 1
  python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if d.get("installed") and not d.get("maintenance") else 1)' "$j" 2>/dev/null
}
t_n8n() {
  local hp; hp=$(hostport n8n 5678/tcp) || return 1
  curl -sf -m 5 "http://$hp/healthz" >/dev/null && [ "$(docker inspect -f '{{.State.Health.Status}}' n8n)" = healthy ]
}
t_litellm() {  # Liveness + Minimalaufruf claude-haiku; Master-Key per Header-Datei, nicht in der Kommandozeile
  local key c
  curl -sf -m 10 "http://$H:4000/health/liveliness" >/dev/null || return 1
  key=$(envwert "$HOME/litellm/.env" LITELLM_MASTER_KEY); [ -n "$key" ] || return 1
  c=$(curl -s -m 60 -o "$tmp/l.json" -w '%{http_code}' -H @<(printf 'Authorization: Bearer %s\nContent-Type: application/json\n' "$key") \
      -d '{"model":"claude-haiku","max_tokens":5,"messages":[{"role":"user","content":"Antworte nur mit OK."}]}' \
      "http://$H:4000/v1/chat/completions")
  [ "$c" = 200 ]
}
teste() {  # $1 Dienst: Test mit Wartezeit (Container braucht Zeit zum Starten)
  local f=${TEST[$1]} i
  for i in $(seq 1 18); do "$f" && return 0; sleep 10; done
  return 1
}

# ------------------------------------------------------------------ Ollama-Referenz einmalig anlegen
if [ "$modus" = referenz ]; then
  [ -e "$OLLAMA_REF" ] && { echo "Referenz existiert schon: $OLLAMA_REF (zum Neuanlegen zuerst von Hand entfernen)"; exit 1; }
  mkdir -p "$(dirname "$OLLAMA_REF")"
  ollama_embed "$tmp/e.json" || { echo "Einbettung fehlgeschlagen"; exit 1; }
  ov=$(curl -s -m 5 "http://$H:11434/api/version")
  python3 - "$tmp/e.json" "$OLLAMA_REF" "$ov" "$OLLAMA_SATZ" <<'PY'
import datetime, json, sys
v = json.load(open(sys.argv[1]))["embeddings"][0]
if len(v) != 1024:
    sys.exit(f"Laenge {len(v)} statt 1024")
json.dump({"modell": "bge-m3", "text": sys.argv[4], "ollama": json.loads(sys.argv[3]).get("version"),
           "erstellt": datetime.datetime.now().isoformat(timespec="seconds"), "vektor": v},
          open(sys.argv[2], "w"))
print(f"Referenz gespeichert: {sys.argv[2]} (1024 Werte, Ollama {json.loads(sys.argv[3]).get('version')})")
PY
  t_ollama && echo "Kontrolle: t_ollama gruen"
  rm -rf "$tmp"; exit 0
fi

# ------------------------------------------------------------------ Plan
declare -A ALT NEU ART INFO
plane() {
  local n=$1 t j
  t=$(tag_in_datei "$n"); ALT[$n]=$t; NEU[$n]=""; ART[$n]=keine; INFO[$n]=""
  if [ -n "$version" ]; then
    if [ "$n" = litellm ] && [[ "$LITELLM_VERBOTEN" == *" $version "* ]]; then INFO[$n]="VERBOTEN: LiteLLM $version ist kompromittiert"; return; fi
    [ "$version" = "$t" ] && { INFO[$n]="bereits $t"; return; }
    NEU[$n]=$version; ART[$n]=version; INFO[$n]="--version"; return
  fi
  if [ "${LINIE[$n]}" = "-" ]; then INFO[$n]="nur mit --version (Freigabe)"; return; fi
  local id digs; id=$(docker inspect -f '{{.Image}}' "$n" 2>/dev/null || true)
  digs=$(docker image inspect -f '{{join .RepoDigests ","}}' "$id" 2>/dev/null || true)
  j=$(python3 "$NV" "${IMG[$n]}" "$t" "${LINIE[$n]}" "$KARENZ" "$id,$digs")
  local teile=()
  mapfile -t teile < <(python3 -c '
import json, sys
d = json.loads(sys.argv[1])
info = []
alter = d.get("alter_tage")
if alter is not None:
    info.append(str(alter) + " Tage alt")
if d.get("zu_jung"):
    info.append("wartet: " + ", ".join(str(t) + " (" + str(a) + " T)" for t, a in d["zu_jung"]))
if d.get("fehler"):
    info.append("FEHLER " + d["fehler"])
print(d.get("neu") or "")
print(d.get("art") or "keine")
print("; ".join(info))' "$j")
  NEU[$n]=${teile[0]:-}; ART[$n]=${teile[1]:-keine}; INFO[$n]=${teile[2]:-}
}

if [ "$modus" = update ]; then
  exec 9>"$LOCK"
  flock -n 9 || { log "Ein anderer Lauf ist aktiv – Abbruch"; exit 3; }
  exec > >(tee -a "$LOG") 2>&1
  log "=== dahub-update ${gruppe:+--gruppe $gruppe}${dienst:+--dienst $dienst}${version:+ --version $version} ==="
fi
for n in "${auswahl[@]}"; do plane "$n"; done
faellig=()
printf '%-13s %-12s %-12s %-8s %s\n' DIENST LAEUFT NEU ART HINWEIS
for n in "${auswahl[@]}"; do
  printf '%-13s %-12s %-12s %-8s %s\n' "$n" "${ALT[$n]}" "${NEU[$n]:--}" "${ART[$n]}" "${INFO[$n]}"
  [ -n "${NEU[$n]}" ] && faellig+=("$n")
done
if [ "$modus" = pruefen ]; then
  echo; echo "Modus --pruefen: nichts veraendert. Faellig: ${faellig[*]:-keine}"
  rm -rf "$tmp"; exit 0
fi

# ================================================================== Ab hier Aenderungen
if [ ${#faellig[@]} -eq 0 ]; then
  log "Nichts zu tun."
  [ -n "$gruppe" ] && melden "da-hub: Updates" "Keine Updates faellig (${#auswahl[@]} Dienste geprueft)." low
  rm -rf "$tmp"; exit 0
fi

ok=(); rot=(); zurueck=(); nc_wartung=0; flag_von_uns=0
aufraeumen() {
  local rc=$?
  if [ "$flag_von_uns" = 1 ]; then
    if [ "$nc_wartung" = 1 ]; then log "Wartungsflag bleibt (Nextcloud im Wartungsmodus)"; else rm -f "$FLAG"; log "Wartungsflag entfernt"; fi
  fi
  rm -rf "$tmp"
  if [ "$rc" -ne 0 ] && [ "${fertig:-0}" != 1 ]; then
    melden "da-hub: Update ABGEBROCHEN" "dahub-update brach unerwartet ab (rc=$rc). Log: $LOG" urgent
  fi
}
trap aufraeumen EXIT
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM

# ------------------------------------------------------------------ Pause
touch "$FLAG"; flag_von_uns=1
log "Wartungsflag gesetzt: $FLAG"
for u in $PAUSE_UNITS; do
  systemctl cat "$u" 2>/dev/null | grep -qF "ConditionPathExists=!$FLAG" || { log "ABBRUCH: $u kennt das Wartungsflag nicht (Drop-in fehlt)"; exit 1; }
  [ "$(systemctl show -p NeedDaemonReload --value "$u")" = no ] || { log "ABBRUCH: $u braucht daemon-reload"; exit 1; }
done
log "Drop-ins geladen: $PAUSE_UNITS"

braucht_worker_pause=0
for n in "${faellig[@]}"; do [[ "$WORKER_DIENSTE" == *" $n "* ]] && braucht_worker_pause=1; done
if [ "$braucht_worker_pause" = 1 ]; then
  log "Warte auf Ende laufender Worker-/Scan-/Cron-Laeufe (max. $((WORKER_MAX / 60)) min) ..."
  start=$(date +%s)
  while systemctl show -p ActiveState --value $PAUSE_UNITS | grep -qvxE 'inactive|failed'; do
    [ $(( $(date +%s) - start )) -lt "$WORKER_MAX" ] || { log "ABBRUCH: Worker nach $((WORKER_MAX / 60)) min noch aktiv"; melden "da-hub: Update abgebrochen" "Worker lief nach $((WORKER_MAX / 60)) min noch – nichts aktualisiert." high; exit 1; }
    sleep 30
  done
  haengend=$(docker exec postgres-vector psql -U dahub -d knowledge -qAtc "UPDATE file_jobs SET status='pending' WHERE status='processing' RETURNING id" | grep -c . || true)
  log "Worker ruht; haengende processing-Jobs auf pending gesetzt: $haengend"
fi

# ------------------------------------------------------------------ Hilfen fuer Updates
setze_tag() {  # $1 Dienst $2 alter Tag $3 neuer Tag – genau eine image-Zeile muss passen
  local f="${DIR[$1]}/docker-compose.yml" alt="${IMG[$1]}:$2" neu="${IMG[$1]}:$3"
  [ "$(grep -cE "^[[:space:]]*image:[[:space:]]*[\"']?${alt//./\\.}[\"']?[[:space:]]*\$" "$f")" = 1 ] || return 1
  sed -i -E "s#^([[:space:]]*image:[[:space:]]*)[\"']?${alt//./\\.}[\"']?[[:space:]]*\$#\1$neu#" "$f"
  grep -qE "^[[:space:]]*image: ${neu//./\\.}\$" "$f"
}
dryrun_ok() {  # nur die genannten Dienste duerfen betroffen sein, kein neues Netz/Volume
  local d; d=$(compose "$1" up -d --no-deps --dry-run "${@:2}" 2>&1) || return 1
  grep -Eiq '(network|volume).*creat' <<<"$d" && return 1
  local fremd; fremd=$(grep -Ei 'container' <<<"$d" | grep -vE "$(IFS='|'; echo "${*:2}")" || true)
  [ -z "$fremd" ]
}
commit_repo() {  # $1 Dienst, $2 Text
  cp "${DIR[$1]}/docker-compose.yml" "$REPO/${REPOF[$1]}"
  git -C "$REPO" add "${REPOF[$1]}"
  git -C "$REPO" commit -q -m "dahub-update: $2" -m "Automatisch durch dahub-update.sh, Tests gruen." \
    -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" || log "WARNUNG: Commit fehlgeschlagen"
}

# ------------------------------------------------------------------ ein Dienst (ausser Nextcloud)
aktualisiere() {
  local n=$1 alt=${ALT[$1]} neu=${NEU[$1]} f="${DIR[$1]}/docker-compose.yml" alt_id neu_id
  log "--- $n: $alt -> $neu (${ART[$n]})"
  alt_id=$(docker inspect -f '{{.Image}}' "$n")
  docker tag "$alt_id" "dahub-rueckfall/$n:vorher"
  cp "$f" "$tmp/$n.yml.vorher"
  if ! docker pull -q "${IMG[$n]}:$neu" >/dev/null; then log "$n: Pull fehlgeschlagen – uebersprungen"; rot+=("$n (Pull)"); return; fi
  neu_id=$(docker image inspect -f '{{.Id}}' "${IMG[$n]}:$neu")
  if [ "$neu_id" = "$alt_id" ]; then log "$n: Image unveraendert – nichts zu tun"; return; fi
  if [ "$neu" != "$alt" ]; then setze_tag "$n" "$alt" "$neu" || { log "$n: Tag nicht setzbar – uebersprungen"; cp "$tmp/$n.yml.vorher" "$f"; rot+=("$n (Compose)"); return; }; fi
  if ! dryrun_ok "$n" "$n"; then log "$n: Dry-Run betrifft mehr als $n – uebersprungen"; cp "$tmp/$n.yml.vorher" "$f"; rot+=("$n (Dry-Run)"); return; fi
  local grund
  if compose "$n" up -d --no-deps "$n"; then
    if teste "$n"; then
      log "$n: Test gruen ($(docker inspect -f '{{.Image}}' "$n"))"
      if [ "${ART[$n]}" = neubau ]; then ok+=("$n $neu (Neubau)"); else ok+=("$n $alt→$neu"); fi
      commit_repo "$n" "$n $alt -> $neu"
      return
    fi
    grund="Test rot"
  else
    grund="compose up fehlgeschlagen"
  fi
  log "$n: $grund – Rueckfall auf $alt ($alt_id)"
  cp "$tmp/$n.yml.vorher" "$f"
  docker tag "$alt_id" "${IMG[$n]}:$alt"          # bei Neubau zeigt der Tag sonst auf das neue Image
  if compose "$n" up -d --no-deps "$n" && teste "$n"; then
    zurueck+=("$n ($neu: $grund, zurueck auf $alt)")
    melden "da-hub: Update zurueckgenommen" "$n $neu: $grund. Zurueck auf $alt, Test wieder gruen." high
  else
    rot+=("$n (auch nach Rueckfall rot!)")
    melden "da-hub: $n GESTOERT" "$n $neu: $grund, Rueckfall auf $alt ebenfalls rot. Bitte sofort pruefen. Log: $LOG" urgent
  fi
}

# ------------------------------------------------------------------ Nextcloud (nextcloud + nextcloud-db)
aktualisiere_nextcloud() {
  local dienste=() n f="${DIR[nextcloud]}/docker-compose.yml" dump tabellen create soll
  for n in nextcloud-db nextcloud; do [ -n "${NEU[$n]:-}" ] && dienste+=("$n"); done
  log "--- Nextcloud: ${dienste[*]}"
  cp "$f" "$tmp/nextcloud.yml.vorher"
  for n in "${dienste[@]}"; do
    docker tag "$(docker inspect -f '{{.Image}}' "$n")" "dahub-rueckfall/$n:vorher"
    docker pull -q "${IMG[$n]}:${NEU[$n]}" >/dev/null || { log "$n: Pull fehlgeschlagen – Nextcloud uebersprungen"; rot+=("$n (Pull)"); return; }
    if [ "${NEU[$n]}" != "${ALT[$n]}" ]; then setze_tag "$n" "${ALT[$n]}" "${NEU[$n]}" || { cp "$tmp/nextcloud.yml.vorher" "$f"; rot+=("$n (Compose)"); return; }; fi
  done
  dryrun_ok nextcloud nextcloud-db nextcloud || { cp "$tmp/nextcloud.yml.vorher" "$f"; log "Nextcloud: Dry-Run unerwartet – uebersprungen"; rot+=("nextcloud (Dry-Run)"); return; }

  occ maintenance:mode --on; nc_wartung=1
  sleep 5
  mkdir -p "$BACKUP"; chmod 700 "$BACKUP"
  dump=$BACKUP/nextcloud-$(date +%Y%m%d-%H%M).sql
  tabellen=$(docker exec nextcloud-db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mariadb -u"$MYSQL_USER" -N -B "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type=\"BASE TABLE\""')
  if ! docker exec nextcloud-db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mariadb-dump -u"$MYSQL_USER" --single-transaction --no-tablespaces --quick --default-character-set=utf8mb4 "$MYSQL_DATABASE"' > "$dump"; then
    rm -f "$dump"; cp "$tmp/nextcloud.yml.vorher" "$f"; occ maintenance:mode --off; nc_wartung=0
    rot+=("nextcloud (Dump)"); melden "da-hub: Nextcloud-Update ausgelassen" "Dump fehlgeschlagen – nichts veraendert, Wartungsmodus wieder aus." high; return
  fi
  create=$(grep -c '^CREATE TABLE' "$dump" || true)
  if [ "$create" != "$tabellen" ] || ! tail -1 "$dump" | grep -q '^-- Dump completed'; then
    cp "$tmp/nextcloud.yml.vorher" "$f"; occ maintenance:mode --off; nc_wartung=0
    rot+=("nextcloud (Dump unvollstaendig)"); melden "da-hub: Nextcloud-Update ausgelassen" "Dump unvollstaendig ($create/$tabellen) – nichts veraendert." high; return
  fi
  if ! docker exec nextcloud cat /var/www/html/version.php > "$dump.version.php" || ! grep -q 'OC_Version' "$dump.version.php"; then
    rm -f "$dump.version.php"; cp "$tmp/nextcloud.yml.vorher" "$f"; occ maintenance:mode --off; nc_wartung=0
    rot+=("nextcloud (version.php nicht gesichert)")
    melden "da-hub: Nextcloud-Update ausgelassen" "Sicherung von version.php fehlgeschlagen – nichts veraendert, Wartungsmodus wieder aus. Dump liegt vor: $dump" high
    return
  fi
  chmod 600 "$dump" "$dump.version.php"
  log "Dump: $dump ($(du -h "$dump" | cut -f1), $create Tabellen) + version.php"
  ls -1t "$BACKUP"/nextcloud-2*.sql 2>/dev/null | tail -n +$((DUMPS_BEHALTEN + 1)) | while read -r alt; do
    rm -f -- "$alt" "$alt.version.php"; log "alter Dump entfernt: $alt"
  done

  if ! compose nextcloud up -d --no-deps nextcloud-db nextcloud; then
    occ maintenance:mode --on >/dev/null 2>&1 || true; nc_wartung=1
    rot+=("nextcloud (compose up fehlgeschlagen, Wartungsmodus AN)")
    melden "da-hub: NEXTCLOUD GESTOERT" "Update ${dienste[*]}: docker compose up fehlgeschlagen. Wartungsmodus AN (falls erreichbar), kein Rueckfall. Dump: $dump. Log: $LOG" urgent
    return
  fi
  # Erst warten, bis der Container gesund ist: Das Image fuehrt bei neuer Version selbst occ upgrade aus.
  # Erst danach needsDbUpgrade pruefen, damit kein zweites Upgrade parallel laeuft.
  local i h=""
  for i in $(seq 1 120); do
    h=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' nextcloud 2>/dev/null || true)
    [ "$h" = healthy ] && break
    sleep 5
  done
  if [ "$h" != healthy ]; then
    occ maintenance:mode --on >/dev/null 2>&1 || true; nc_wartung=1
    rot+=("nextcloud (nach 10 min nicht healthy: $h, Wartungsmodus AN)")
    melden "da-hub: NEXTCLOUD GESTOERT" "Update ${dienste[*]}: Container nach 10 min nicht healthy ($h). Wartungsmodus AN, kein Rueckfall. Dump: $dump. Log: $LOG" urgent
    return
  fi
  log "Nextcloud healthy"
  if occ status --output=json 2>/dev/null | grep -q '"needsDbUpgrade":true'; then
    log "needsDbUpgrade=true -> occ upgrade"
    occ upgrade || log "WARNUNG: occ upgrade mit Fehler beendet"
  fi
  occ maintenance:mode --off || true
  soll=$(tag_in_datei nextcloud)
  if teste nextcloud; then
    nc_wartung=0
    for n in "${dienste[@]}"; do ok+=("$n ${ALT[$n]}→${NEU[$n]}"); done
    commit_repo nextcloud "Nextcloud: $(for n in "${dienste[@]}"; do printf '%s %s -> %s; ' "$n" "${ALT[$n]}" "${NEU[$n]}"; done)"
    log "Nextcloud: Tests gruen ($soll)"
  else
    occ maintenance:mode --on || true; nc_wartung=1
    rot+=("nextcloud (Test rot, Wartungsmodus AN)")
    melden "da-hub: NEXTCLOUD GESTOERT" "Update ${dienste[*]} – Test rot. Wartungsmodus bleibt AN, kein Rueckfall. Dump: $dump (+ .version.php). Rueckfall-Images: dahub-rueckfall/<dienst>:vorher. Worker bleibt pausiert." urgent
  fi
}

# ------------------------------------------------------------------ Ausfuehren
for n in "${faellig[@]}"; do
  case "$n" in nextcloud|nextcloud-db) continue ;; esac
  aktualisiere "$n"
done
for n in "${faellig[@]}"; do
  case "$n" in nextcloud|nextcloud-db) aktualisiere_nextcloud; break ;; esac
done

git -C "$REPO" push -q 2>/dev/null || log "WARNUNG: git push fehlgeschlagen"
fertig=1
zusammen="aktualisiert: ${#ok[@]}"
[ ${#ok[@]} -gt 0 ] && zusammen+=" (${ok[*]})"
[ ${#zurueck[@]} -gt 0 ] && zusammen+="; zurueckgenommen: ${zurueck[*]}"
[ ${#rot[@]} -gt 0 ] && zusammen+="; FEHLER: ${rot[*]}"
log "Ergebnis: $zusammen"
if [ ${#rot[@]} -eq 0 ] && [ ${#zurueck[@]} -eq 0 ]; then
  melden "da-hub: Updates" "${#ok[@]} Dienste aktualisiert, alle Tests gruen. ${ok[*]}" low
  exit 0
fi
[ ${#rot[@]} -eq 0 ] || melden "da-hub: Updates mit Fehlern" "$zusammen" high
exit 1
