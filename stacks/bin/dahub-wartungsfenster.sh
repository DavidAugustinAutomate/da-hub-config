#!/usr/bin/env bash
# dahub-wartungsfenster.sh – Schritte OHNE sudo fuer das Wartungsfenster (Docker/containerd, Tailscale, Neustart).
# Die sudo-Befehle fuehrt David einzeln in seiner eigenen Sitzung aus (Liste unten bzw. im Beschrieb).
#
#   dahub-wartungsfenster.sh vorher        Zustand erfassen, Wartungsflag setzen, laufenden Worker abwarten
#   dahub-wartungsfenster.sh pruefen       Zwischenpruefung nach einem sudo-Schritt (Versionen, Container, Tailscale, DNS)
#   dahub-wartungsfenster.sh vor-neustart  Wartungsflag entfernen (es wuerde den Neustart ueberdauern) – direkt vor 'sudo reboot'
#   dahub-wartungsfenster.sh nachher       nach dem Neustart: Vergleich mit dem Zustand von 'vorher'
#   (10 min nach dem Neustart meldet ausserdem dahub-selbstpruefung per ntfy)
#
# Reihenfolge (sudo-Befehle einzeln, jeweils danach 'pruefen'):
#   0  sudo -v
#   1  dahub-wartungsfenster.sh vorher
#   2  sudo apt-get install --only-upgrade docker-ce docker-ce-cli docker-ce-rootless-extras docker-buildx-plugin containerd.io
#      -> dahub-wartungsfenster.sh pruefen   (Docker 29.8.1, containerd 2.3.6, alle Container wieder da)
#   3  sudo apt-get install --only-upgrade tailscale
#      ACHTUNG: tailscaled startet neu – eine SSH-Sitzung ueber Tailscale bricht kurz ab.
#      Deshalb in tmux ausfuehren oder ueber das Heimnetz (LAN-IP 192.168.1.198) verbunden sein.
#      -> dahub-wartungsfenster.sh pruefen   (Tailscale 1.102.4, online, resolv.conf von Tailscale)
#   4  dahub-wartungsfenster.sh vor-neustart
#   5  sudo reboot
#   6  nach ca. 10 min: ntfy «Neustart: alles gruen»; dann dahub-wartungsfenster.sh nachher
set -uo pipefail
ST=$HOME/.local/state; FLAG=$ST/dahub-wartung; ORDNER=$ST/wartungsfenster
mkdir -p "$ORDNER"; chmod 700 "$ORDNER"
log() { echo "$(date '+%T') $*"; }

zustand() {  # $1 Zieldatei – nur Namen/Versionen, keine Werte aus Konfigurationen
  {
    echo "zeit $(date '+%F %T')"; echo "kernel $(uname -r)"
    echo "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"
    echo "containerd $(containerd --version 2>/dev/null | awk '{print $3}')"
    echo "tailscale $(tailscale version 2>/dev/null | head -n 1)"
    docker ps -a --format 'container {{.Names}} {{.Image}} {{.State}}' | sort
    systemctl list-unit-files --type=timer --state=enabled --no-legend 'dahub-*.timer' 'wissensbasis-*.timer' | awk '{print "timer", $1}' | sort
    docker exec postgres-vector psql -U dahub -d knowledge -qAt -F ' ' -c "SELECT 'jobs', status, count(*) FROM file_jobs WHERE status IN ('pending','processing','failed') GROUP BY 2 ORDER BY 2" 2>/dev/null
  } > "$1"
}
pruefen() {
  log "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?'), containerd $(containerd --version 2>/dev/null | awk '{print $3}'), Tailscale $(tailscale version 2>/dev/null | head -n 1)"
  log "Dienste: docker $(systemctl is-active docker), containerd $(systemctl is-active containerd), tailscaled $(systemctl is-active tailscaled)"
  local soll=0 laufen=0 krank=()
  while read -r n rp st hl; do
    case "$rp" in always|unless-stopped) ;; *) continue ;; esac
    soll=$((soll + 1)); [ "$st" = running ] && laufen=$((laufen + 1)) || krank+=("$n $st")
    [ "$hl" = unhealthy ] && krank+=("$n unhealthy")
  done < <(docker ps -aq | xargs -r docker inspect -f '{{.Name}} {{.HostConfig.RestartPolicy.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' | sed 's#^/##')
  log "Container: $laufen/$soll laufen ${krank[*]:+– ${krank[*]}}"
  log "Tailscale: $(tailscale status --self --peers=false 2>/dev/null | head -n 1 | awk '{print $1, $2, $NF}')"
  log "DNS: $(head -n 1 /etc/resolv.conf)"
  log "Wartungsflag: $([ -e "$FLAG" ] && echo steht || echo weg)"
}

case "${1:-}" in
  vorher)
    zustand "$ORDNER/vorher.txt"; log "Zustand erfasst: $ORDNER/vorher.txt"
    if [ -e "$FLAG" ]; then log "Wartungsflag steht bereits"; else touch "$FLAG"; log "Wartungsflag gesetzt (Worker, Scan, Nextcloud-Cron pausiert, Ueberwachung schweigt)"; fi
    log "Warte auf Ende laufender Worker-/Scan-/Cron-Laeufe (max. 35 min dank weicher Frist) ..."
    for i in $(seq 420); do
      aktiv=""; for u in wissensbasis-worker wissensbasis-scan nextcloud-cron; do
        case "$(systemctl show -p ActiveState --value $u.service)" in inactive|failed) ;; *) aktiv+="$u " ;; esac; done
      [ -z "$aktiv" ] && break; sleep 5
    done
    [ -z "$aktiv" ] && log "Worker, Scan und Cron ruhen – bereit fuer Schritt 2" || log "ACHTUNG: noch aktiv: $aktiv"
    pruefen ;;
  pruefen) pruefen ;;
  vor-neustart)
    pruefen
    rm -f "$FLAG"; log "Wartungsflag entfernt – jetzt direkt 'sudo reboot' (das Flag wuerde den Neustart ueberdauern)" ;;
  nachher)
    [ -f "$ORDNER/vorher.txt" ] || { log "kein Zustand von 'vorher' gefunden"; exit 1; }
    zustand "$ORDNER/nachher.txt"
    log "Unterschiede vorher -> nachher (ohne Zeit und Job-Zahlen):"
    diff <(grep -vE '^(zeit|jobs) ' "$ORDNER/vorher.txt") <(grep -vE '^(zeit|jobs) ' "$ORDNER/nachher.txt") | sed 's/^/   /'
    pruefen ;;
  *) sed -n '2,23p' "$0"; exit 2 ;;
esac
