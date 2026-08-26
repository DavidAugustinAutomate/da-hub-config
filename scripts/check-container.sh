#!/bin/bash
# Prueft, ob die wichtigen Container laufen. Alarmiert bei Ausfall.

CONTAINER="litellm n8n nextcloud nextcloud-db portainer ntfy"

for c in $CONTAINER; do
  status=$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)
  if [ "$status" != "true" ]; then
    ~/scripts/notify.sh "da-hub: Dienst unten" "Container '$c' laeuft nicht!" urgent
  fi
done
