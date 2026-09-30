#!/usr/bin/env bash
# dahub-wochenbilanz.sh – Montagsbilanz (Timer Mo 08:05), eine Meldung ueber notify.sh:
#   Sonntagslauf von dahub-update.sh (Totmann: fehlt er, wird gewarnt), Container, Indexierung,
#   verfuegbare Updates der Gruppe freigabe (nur Meldung).
#
#   dahub-wochenbilanz.sh              senden, Indexierungsstand fuer die naechste Woche merken
#   dahub-wochenbilanz.sh --anzeigen   nur ausgeben, nichts senden, nichts merken
set -uo pipefail

STATE=$HOME/.local/state
ERG=$STATE/dahub-update-ergebnis-auto
STAND=$STATE/dahub-wochenbilanz.stand
NOTIFY=$HOME/scripts/notify.sh
BIN_DIR=$HOME/stacks/bin
UPDATE=$BIN_DIR/dahub-update.sh
MAX_ALTER=$((48 * 3600))          # Sonntag 03:30 -> Montag 08:05 = rund 29 h
MAX_ATTEMPTS=3                    # wie check-index-fehler.sh

anzeigen=0
case "${1:-}" in
  --anzeigen) anzeigen=1 ;;
  "") ;;
  *) echo "Unbekannte Option: $1"; exit 2 ;;
esac
prio=low; zeilen=()
warnung() { prio=high; }

# ------------------------------------------------------------------ 1 Sonntagslauf
wert() { local w; w=$(sed -n "s/^$1=//p" "$ERG" 2>/dev/null); printf '%s' "${w%%$'\n'*}"; }   # ohne "| head" (SIGPIPE)
if [ ! -f "$ERG" ]; then
  zeilen+=("Updates: KEIN Lauf gefunden – systemctl status dahub-update.timer"); warnung
else
  epoch=$(wert epoch); [[ "$epoch" =~ ^[0-9]+$ ]] || epoch=0
  rc=$(wert rc)
  if [ $(( $(date +%s) - epoch )) -gt "$MAX_ALTER" ]; then
    zeilen+=("Updates: Sonntagslauf FEHLT (letzter Lauf: $(wert zeit))"); warnung
  elif [ "$rc" = 0 ]; then
    zeilen+=("Updates: $(wert text)")
  else
    zeilen+=("Updates: FEHLER (rc=$rc) – $(wert text)"); warnung
  fi
fi

# ------------------------------------------------------------------ 2 Container (erwartet = restart always|unless-stopped)
soll=0; laufen=0; ungesund=0; probleme=()
while read -r name rp st hl; do
  case "$rp" in always|unless-stopped) ;; *) continue ;; esac
  soll=$((soll + 1))
  if [ "$st" = running ]; then laufen=$((laufen + 1)); else probleme+=("$name $st"); fi
  if [ "$hl" = unhealthy ]; then ungesund=$((ungesund + 1)); probleme+=("$name unhealthy"); fi
done < <(docker ps -aq | xargs -r docker inspect -f '{{.Name}} {{.HostConfig.RestartPolicy.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' 2>/dev/null | sed 's#^/##')
if [ "$soll" -eq 0 ]; then
  zeilen+=("Container: nicht abfragbar"); warnung
else
  z="Container: $laufen/$soll laufen, $ungesund ungesund"
  if [ ${#probleme[@]} -gt 0 ]; then z+=" ($(IFS=,; echo "${probleme[*]}"))"; warnung; fi
  zeilen+=("$z")
fi

# ------------------------------------------------------------------ 3 Indexierung
roh=$(docker exec postgres-vector psql -U dahub -d knowledge -qAt -F ' ' -c \
  "SELECT count(*) FILTER (WHERE status='pending'), count(*) FILTER (WHERE status='done'),
          count(*) FILTER (WHERE status='failed' AND attempts >= $MAX_ATTEMPTS) FROM file_jobs" 2>/dev/null)
read -r pending erledigt endg <<<"$roh"
if ! [[ "${pending:-}" =~ ^[0-9]+$ && "${erledigt:-}" =~ ^[0-9]+$ && "${endg:-}" =~ ^[0-9]+$ ]]; then
  zeilen+=("Indexierung: Datenbank nicht abfragbar"); warnung
else
  v_zeit=""; v_done=""; v_endg=""
  [ -f "$STAND" ] && . <(grep -E '^v_(zeit|done|endg)=[0-9: -]*$' "$STAND")
  if [[ "$v_done" =~ ^[0-9]+$ && "$v_endg" =~ ^[0-9]+$ ]]; then
    zeilen+=("Indexierung: pending $pending, done $erledigt (+$((erledigt - v_done))), endgueltig gescheitert $endg (+$((endg - v_endg)) seit $v_zeit)")
  else
    zeilen+=("Indexierung: pending $pending, done $erledigt, endgueltig gescheitert $endg (erste Messung)")
  fi
  if [ "$anzeigen" = 0 ]; then
    printf 'v_zeit=%s\nv_done=%s\nv_endg=%s\n' "$(date '+%F')" "$erledigt" "$endg" > "$STAND.tmp" && mv "$STAND.tmp" "$STAND"
  fi
fi

# ------------------------------------------------------------------ 4 Verfuegbare Updates (Gruppe freigabe, nur Meldung)
if tab=$("$UPDATE" --pruefen --gruppe freigabe 2>&1); then
  verf=$(awk 'NR == 1 { next } /^$/ { exit }
    $3 != "-" { v = ($2 == $3) ? $3 " (Neubau" : $2 "→" $3 " (" $4
                s = s sep $1 " " v (index($0, "von Hand") ? ", von Hand" : "") ")"; sep = "; " }
    /FEHLER/ { f = f fsep $1; fsep = "," }
    END { if (s == "") s = "nichts Neues"; if (f != "") s = s " – Registry-Fehler: " f; print s }' <<<"$tab")
  zeilen+=("Freigabe verfuegbar: $verf (n8n/LiteLLM: Versions-Check Mo 08:15)")
else
  zeilen+=("Freigabe: Pruefung fehlgeschlagen"); warnung
fi

# ------------------------------------------------------------------ 4b Neustart und offene Pakete (ohne sudo)
REBOOT_DATEI=${DAHUB_REBOOT_DATEI:-/var/run/reboot-required}
if [ -e "$REBOOT_DATEI" ]; then
  laufend=$(uname -r)
  installiert=$(ls -1 /lib/modules 2>/dev/null | sort -V | tail -n 1)
  seit=$(date -r "$REBOOT_DATEI" '+%d.%m.%Y %H:%M')
  zeilen+=("Neustart ausstehend seit $seit, Kernel laufend $laufend, installiert ${installiert:-?}")
fi
pakete=$(LC_ALL=C apt list --upgradable 2>/dev/null | python3 -c '   # LC_ALL=C: Server ist deutsch ("aktualisierbar von")
import collections, sys
z = collections.Counter()
for zeile in sys.stdin:
    if "/" not in zeile or "upgradable" not in zeile:
        continue
    name, rest = zeile.split("/", 1)
    quellen = rest.split(" ", 1)[0]
    if name.startswith(("docker-", "containerd")):
        z["Docker"] += 1
    elif name.startswith("tailscale"):
        z["Tailscale"] += 1
    elif "-security" in quellen:
        z["Debian-Sicherheit"] += 1
    else:
        z["Debian"] += 1
reihe = ["Debian-Sicherheit", "Debian", "Docker", "Tailscale"]
print(", ".join(f"{k} {z[k]}" for k in reihe if z[k]))' 2>/dev/null)
[ -n "$pakete" ] && zeilen+=("Offene Paket-Aktualisierungen: $pakete")

# ------------------------------------------------------------------ 5 Hauptversionen der Gruppe auto (nur Hinweis, kein Knopf)
# Die Linien in dienste.conf halten die Gruppe auto innerhalb ihrer Hauptversion; ein Sprung
# (erste Versionszahl) wird hier nur gemeldet und bleibt eine bewusste Entscheidung von Hand.
haupt=$(python3 - "$BIN_DIR/dienste.conf" "$BIN_DIR/neue-version.py" <<'PY' 2>/dev/null
import json, re, subprocess, sys
conf, nv = sys.argv[1], sys.argv[2]
hinweise = []
for zeile in open(conf, encoding="utf-8"):
    t = zeile.split()
    if len(t) < 5 or t[0].startswith("#") or t[4] != "auto" or t[1] == "-":
        continue
    dienst, image = t[0], t[2]
    try:
        cfg = subprocess.run(["docker", "inspect", "-f", "{{.Config.Image}}", dienst], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        continue
    tag = cfg.rsplit(":", 1)[1] if ":" in cfg.split("/")[-1] else ""
    m = re.fullmatch(r"(v?)(\d+)\.\d+\.\d+", tag)
    if not m:
        continue  # z. B. libreoffice 3.19: keine dreiteilige Version
    praefix, major = m.group(1), int(m.group(2))
    linie = "^" + re.escape(praefix) + r"(?!" + str(major) + r"\.)\d+\.\d+\.\d+$"
    try:
        aus = subprocess.run(["python3", nv, image, tag, linie, "0", ""], capture_output=True, text=True, timeout=300).stdout
        d = json.loads(aus)
    except Exception:
        continue
    neu = d.get("neu")
    if neu and int(re.match(r"v?(\d+)", neu).group(1)) > major:
        hinweise.append(f"{dienst} {tag} -> {neu}")
print("; ".join(hinweise))
PY
)
[ -n "$haupt" ] && zeilen+=("Hauptversion verfuegbar (nur Hinweis, von Hand): $haupt")

# ------------------------------------------------------------------ Meldung
text=$(printf '%s\n' "${zeilen[@]}")
if [ "$anzeigen" = 1 ]; then
  echo "[$prio] da-hub: Wochenbilanz"; echo "$text"; exit 0
fi
"$NOTIFY" "da-hub: Wochenbilanz" "$text" "$prio"
