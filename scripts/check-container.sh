#!/bin/bash
# Prueft, ob die wichtigen Container laufen UND erreichbar sind.
#
# Aenderungen 09.09.2026:
#   - Stack "wissensdatenbank" und Gotenberg ergaenzt (fehlten komplett)
#   - Wiederholungssperre gegen Meldungsfluten bei Dauerausfall
#   - Entwarnung, wenn ein Dienst zurueckkommt
#   - Erreichbarkeitspruefung: Ein Container kann laufen (.State.Running = true)
#     und trotzdem keine Ports veroeffentlichen. Genau das ist am 09.09. nach
#     einem Neustart passiert -- alle vier Container des Stacks
#     "wissensdatenbank" liefen, waren aber nicht erreichbar. Worker und
#     Telegram-Bot fielen aus, die Ueberwachung meldete nichts.

# Container ohne Portpruefung (interne Dienste ohne veroeffentlichten Port)
CONTAINER="nextcloud-db"

# Container mit Portpruefung: "name:adresse:port"
DIENSTE="
litellm:100.93.33.0:4000
n8n:127.0.0.1:5678
nextcloud:127.0.0.1:8080
portainer:127.0.0.1:9443
ntfy:127.0.0.1:9092
gotenberg:127.0.0.1:3000
postgres-vector:100.93.33.0:5432
ollama:100.93.33.0:11434
docling:100.93.33.0:5001
libreoffice:100.93.33.0:2004
"

# Erneute Meldung fruehestens nach dieser Zeit (Sekunden). 6 Stunden =
# hoechstens 4 Meldungen pro Tag und Dienst.
WIEDERHOLUNG=21600

ZUSTAND="/home/david/.local/state/dahub-container"
mkdir -p "$ZUSTAND"

JETZT=$(date +%s)

# ---------------------------------------------------------------------------
melde_problem() {
    # $1 = Kennung (Dateiname), $2 = Klartext fuer die Meldung
    local kennung="$1" text="$2"
    local marke="${ZUSTAND}/${kennung}.down"

    if [ -f "$marke" ]; then
        local seit letzte
        seit=$(cat "$marke" 2>/dev/null || echo "$JETZT")
        letzte=$(stat -c %Y "$marke" 2>/dev/null || echo 0)
        if [ $((JETZT - letzte)) -ge "$WIEDERHOLUNG" ]; then
            ~/scripts/notify.sh "da-hub: weiterhin gestoert" \
                "${text} (seit $(( (JETZT - seit) / 60 )) Minuten)" urgent
            touch "$marke"
        fi
    else
        echo "$JETZT" > "$marke"
        ~/scripts/notify.sh "da-hub: Stoerung" "$text" urgent
    fi
}

melde_entwarnung() {
    local kennung="$1" name="$2"
    local marke="${ZUSTAND}/${kennung}.down"
    [ -f "$marke" ] || return 0
    local seit
    seit=$(cat "$marke" 2>/dev/null || echo "$JETZT")
    rm -f "$marke"
    ~/scripts/notify.sh "da-hub: wieder in Ordnung" \
        "${name} laeuft wieder (Stoerung ca. $(( (JETZT - seit) / 60 )) Minuten)." \
        default
}

laeuft() {
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
}
# ---------------------------------------------------------------------------

# Wartungsflag von dahub-update.sh: waehrend eines Updates nicht melden.
# Besteht das Flag laenger als WARTUNG_MAX, wird das gemeldet und normal geprueft.
WARTUNG="/home/david/.local/state/dahub-wartung"
WARTUNG_MAX=10800
if [ -e "$WARTUNG" ]; then
    alter=$(( JETZT - $(stat -c %Y "$WARTUNG" 2>/dev/null || echo "$JETZT") ))
    [ "$alter" -lt "$WARTUNG_MAX" ] && exit 0
    melde_problem "wartungsflag" "Wartungsflag besteht seit $((alter / 60)) Minuten - dahub-update haengt oder wurde nicht sauber beendet. Ueberwachung laeuft trotzdem."
else
    melde_entwarnung "wartungsflag" "Die Wartung (Wartungsflag)"
fi

# Container ohne Portpruefung
for c in $CONTAINER; do
    if laeuft "$c"; then
        melde_entwarnung "$c" "Container '${c}'"
    else
        melde_problem "$c" "Container '${c}' laeuft nicht!"
    fi
done

# Container mit Portpruefung
for eintrag in $DIENSTE; do
    name="${eintrag%%:*}"
    rest="${eintrag#*:}"
    adresse="${rest%:*}"
    port="${rest##*:}"

    if ! laeuft "$name"; then
        melde_problem "$name" "Container '${name}' laeuft nicht!"
        continue
    fi

    # Laeuft -- aber antwortet er auch?
    if timeout 5 bash -c "</dev/tcp/${adresse}/${port}" 2>/dev/null; then
        melde_entwarnung "$name" "Container '${name}'"
    else
        melde_problem "$name" \
            "Container '${name}' laeuft, ist aber auf ${adresse}:${port} NICHT erreichbar. Vermutlich fehlt die Portveroeffentlichung -- Stack neu erstellen."
    fi
done
