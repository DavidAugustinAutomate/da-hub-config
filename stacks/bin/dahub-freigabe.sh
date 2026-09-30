#!/usr/bin/env bash
# dahub-freigabe.sh <angebots-id> – Knopf «Einspielen» (Phase 4).
# Gestartet von der User-Unit dahub-freigabe@<id>.service. Einziges Argument ist die
# Angebots-ID; Dienst und Version liest das Skript aus update_angebote, nie von aussen.
# Ablauf: Status 'laeuft' pruefen -> dahub-update.sh --simulieren -> bei Gruen echter Lauf.
# Ergebnis zurueck in update_angebote (gemeldet=false); der da-agent meldet es im Chat.
set -uo pipefail
umask 077
B=${DAHUB_BIN:-/home/david/stacks/bin}
DB_CONTAINER=${DAHUB_DB_CONTAINER:-postgres-vector}

id=${1:-}
[[ "$id" =~ ^[0-9]{1,12}$ ]] || { echo "dahub-freigabe: ungueltige Angebots-ID" >&2; exit 2; }

q() { docker exec -i "$DB_CONTAINER" psql -U dahub -d knowledge -v ON_ERROR_STOP=1 -qAt -F '|' "$@"; }
setze() {  # $1 Status, $2 Ergebnistext – nur aus 'laeuft' heraus
  q -v id="$id" -v st="$1" -v erg="${2:0:500}" >/dev/null <<'SQL'
UPDATE update_angebote SET status = :'st', ergebnis = :'erg', gemeldet = false, aktualisiert = now()
WHERE id = :'id'::bigint AND status = 'laeuft';
SQL
}
wieder_offen() {  # anderer Lauf aktiv: Angebot bleibt offen, Hinweis an den Chat
  q -v id="$id" -v erg="$1" >/dev/null <<'SQL'
UPDATE update_angebote SET status = 'offen', laeuft_seit = NULL, ergebnis = :'erg', gemeldet = false,
       aktualisiert = now()
WHERE id = :'id'::bigint AND status = 'laeuft';
SQL
}

zeile=$(q -v id="$id" <<'SQL'
SELECT dienst, version_neu, status FROM update_angebote WHERE id = :'id'::bigint;
SQL
) || { echo "dahub-freigabe: Datenbank nicht erreichbar" >&2; exit 1; }
[ -n "$zeile" ] || { echo "dahub-freigabe: Angebot $id unbekannt" >&2; exit 1; }
IFS='|' read -r dienst version status <<<"$zeile"

[ "$status" = laeuft ] || { echo "dahub-freigabe: Angebot $id hat Status '$status' – nichts zu tun"; exit 0; }
case "$dienst" in n8n|litellm) ;; *) setze fehler "Dienst '$dienst' ist fuer den Knopf nicht freigegeben"; exit 1 ;; esac
[[ "$version" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]] || { setze fehler "Ungueltige Version im Angebot"; exit 1; }
if [ "$dienst" = litellm ]; then
  case "${version#v}" in 1.82.7|1.82.8) setze fehler "LiteLLM $version ist gesperrt (kompromittiert)"; exit 1 ;; esac
fi

lauf=$(mktemp); trap 'rm -f "$lauf"' EXIT
zusammenfassung() { grep -E ' (Ergebnis|ABBRUCH|FEHLER): ' "$lauf" | tail -2 | sed -E 's/^[0-9-]+ [0-9:]+ //' | tr '\n' ' ' | cut -c1-400; }

echo "Angebot $id: $dienst $version – Simulation"
"$B/dahub-update.sh" --simulieren --dienst "$dienst" --version "$version" >"$lauf" 2>&1; rc=$?
cat "$lauf"
if [ "$rc" = 3 ]; then wieder_offen "Anderer Lauf aktiv, bitte später erneut."; exit 0; fi
if [ "$rc" != 0 ]; then setze simulation_rot "Simulation rot (rc=$rc): $(zusammenfassung)"; exit 1; fi

echo "Angebot $id: $dienst $version – echter Lauf"
"$B/dahub-update.sh" --still --dienst "$dienst" --version "$version" >"$lauf" 2>&1; rc=$?
cat "$lauf"
if [ "$rc" = 3 ]; then wieder_offen "Anderer Lauf aktiv, bitte später erneut."; exit 0; fi
if [ "$rc" = 0 ]; then setze erledigt "$(zusammenfassung)"; exit 0; fi
setze fehler "rc=$rc: $(zusammenfassung) – Log: ~/.local/state/dahub-update.log"
exit 1
