#!/usr/bin/env bash
# dahub-selbstpruefung.sh – Selbstpruefung nach jedem Neustart (auch nach Stromausfall).
# Gestartet von der User-Unit dahub-selbstpruefung.timer (OnBootSec=10min; dank Linger ohne Anmeldung).
# Prueft: alle Funktionstests (dahub-update.sh --tests), Container laufen bzw. healthy,
# dahub- und wissensbasis-Timer aktiv, da-agent aktiv, DNS von Tailscale, kein Wartungsflag,
# laufender Kernel = neuester installierter. Ergebnis als EINE ntfy-Meldung:
#   «Neustart: alles gruen» (default) bzw. die roten Punkte (high).
#   dahub-selbstpruefung.sh              pruefen und melden
#   dahub-selbstpruefung.sh --anzeigen   nur ausgeben, nichts senden
set -uo pipefail
B=${DAHUB_BIN:-$HOME/stacks/bin}
NOTIFY=${DAHUB_NOTIFY:-$HOME/scripts/notify.sh}
FLAG=${DAHUB_FLAG:-$HOME/.local/state/dahub-wartung}
RESOLV=${DAHUB_RESOLV:-/etc/resolv.conf}
MODULE=${DAHUB_MODULE:-/lib/modules}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

anzeigen=0
case "${1:-}" in --anzeigen) anzeigen=1 ;; "") ;; *) echo "Unbekannte Option: $1"; exit 2 ;; esac
rot=(); gruen=0
ok() { gruen=$((gruen + 1)); }

# 1 Funktionstests
tests=$("$B/dahub-update.sh" --tests 2>&1); rc=$?
rote=$(awk '$2 == "ROT" {print $1}' <<<"$tests" | paste -sd, -)
if [ "$rc" = 0 ]; then ok; else rot+=("Funktionstests rot: ${rote:-rc=$rc}"); fi

# 2 Container: erwartet = restart always|unless-stopped
soll=0; probleme=()
while read -r name rp st hl; do
  case "$rp" in always|unless-stopped) ;; *) continue ;; esac
  soll=$((soll + 1))
  [ "$st" = running ] || probleme+=("$name $st")
  [ "$hl" = unhealthy ] && probleme+=("$name unhealthy")
done < <(docker ps -aq 2>/dev/null | xargs -r docker inspect -f '{{.Name}} {{.HostConfig.RestartPolicy.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' 2>/dev/null | sed 's#^/##')
if [ "$soll" = 0 ]; then rot+=("Container: nicht abfragbar")
elif [ ${#probleme[@]} -gt 0 ]; then rot+=("Container: $(IFS=,; echo "${probleme[*]}")")
else ok; fi

# 3 Timer (System und User) + da-agent
timer=$(systemctl list-unit-files --type=timer --state=enabled --no-legend 'dahub-*.timer' 'wissensbasis-*.timer' 2>/dev/null | awk '{print $1}')
# ohne den eigenen Timer: er startet diese Pruefung nach dem Neustart; beim Aufruf von Hand ist er
# (bis zum naechsten Neustart) inaktiv, das waere ein falscher roter Punkt
utimer=$(systemctl --user list-unit-files --type=timer --state=enabled --no-legend 'dahub-*.timer' 2>/dev/null | awk '$1 != "dahub-selbstpruefung.timer" {print $1}')
inaktiv=()
for t in $timer; do [ "$(systemctl is-active "$t")" = active ] || inaktiv+=("$t"); done
for t in $utimer; do [ "$(systemctl --user is-active "$t")" = active ] || inaktiv+=("$t (user)"); done
if [ -z "$timer" ]; then rot+=("Timer: keine dahub-/wissensbasis-Timer gefunden")
elif [ ${#inaktiv[@]} -gt 0 ]; then rot+=("Timer inaktiv: $(IFS=,; echo "${inaktiv[*]}")")
else ok; fi
if [ "$(systemctl is-active da-agent.service)" = active ]; then ok; else rot+=("da-agent nicht aktiv"); fi

# 4 DNS: resolv.conf von Tailscale (Punkt K, dhcpcd 'nohook resolv.conf')
kopf=$(head -n 3 "$RESOLV" 2>/dev/null)
if grep -qi 'tailscale' <<<"$kopf" && grep -q '^nameserver 100\.100\.100\.100' "$RESOLV" 2>/dev/null; then ok
else rot+=("DNS: resolv.conf nicht von Tailscale ($(head -n 1 "$RESOLV" 2>/dev/null | cut -c1-60))"); fi

# 5 Wartungsflag
if [ -e "$FLAG" ]; then rot+=("Wartungsflag steht ($FLAG)"); else ok; fi

# 6 Kernel = neuester installierter
laufend=$(uname -r); neuester=$(ls -1 "$MODULE" 2>/dev/null | sort -V | tail -n 1)
if [ "$laufend" = "$neuester" ]; then ok; else rot+=("Kernel laufend $laufend, neuester installiert ${neuester:-?} (Neustart ausstehend)"); fi

# ------------------------------------------------------------------ Meldung
hoch=$(uptime -s 2>/dev/null | cut -c1-16)
if [ ${#rot[@]} -eq 0 ]; then
  titel="da-hub: Neustart"; prio=default
  text="Neustart: alles gruen ($gruen Pruefungen, Kernel $laufend, hochgefahren $hoch)."
else
  titel="da-hub: Neustart – ${#rot[@]} rote Punkte"; prio=high
  text="Neustart: ${#rot[@]} rote Punkte, $gruen gruen (hochgefahren $hoch). $(printf '%s; ' "${rot[@]}")"
fi
if [ "$anzeigen" = 1 ]; then echo "[$prio] $titel"; echo "$text"; echo "--- Funktionstests:"; echo "$tests"; exit 0; fi
"$NOTIFY" "$titel" "$text" "$prio"
[ ${#rot[@]} -eq 0 ]
