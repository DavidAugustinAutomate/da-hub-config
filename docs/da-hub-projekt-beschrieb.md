# Projekt-Beschrieb: Automatisierungshub «da-hub»

*Kontextdokument für künftige Chats. Stand: 30.09.2026. Ersetzt den Beschrieb vom 15.09.2026.*
*Punkte mit «(unbestätigt)» stammen aus älteren Sessions und wurden seither nicht erneut geprüft.*

---

## Was das ist

Privater, immer laufender Automatisierungs- und KI-Server auf eigener Hardware. Hobby-Projekt, auch geschäftlich genutzt, aber **unabhängig von der KGAG-Infrastruktur**. Leitgedanke: **anbieterunabhängige Plattform** – KI ist einer von mehreren Diensten. Laptop und iPhone sind Bedienoberflächen; der Server ist das System of Record und läuft 24/7.

Roter Faden: wiederkehrende Aufgaben automatisieren, primär rund um Dokumente und Mails, plus ein persönlicher Agent mit Zugriff auf die eigene Wissensbasis.

---

## Hardware

- Dell OptiPlex 7070 Micro (refurbished), Intel i5-9500T (6 Kerne, vPro), 32 GB RAM, 1 TB NVMe (WD Blue SN580)
- Service Tag F773F13 · BIOS 1.35.0
- AMT/vPro provisioniert (Out-of-Band-Rettungsanker)
- Headless, nur Strom + Ethernet; «Restore on AC Power» aktiv
- Belegung 27.09.2026: 229 GB von 884 GB (28 %), 611 GB frei

---

## Betriebssystem & Zugriff

- Debian 13 (Trixie), headless · Hostname `da-hub` · Benutzer `david` (sudo) · Zeitzone Europe/Zurich
- LAN-IP `192.168.1.198` (DHCP-Reservation) – LAN-Zugriff auf Dienste gesperrt
- Tailscale-IP `100.93.33.0` · Tailnet-Name `da-hub.taile9dad7.ts.net`
- SSH: `ssh david@100.93.33.0`, nur per Schlüssel

## Sicherheit

- SSH nur per Schlüssel, fail2ban aktiv
- Dienste nur über `tailscale0`; ufw blockiert Heimnetz-Zugriff auf Docker-Ports
- **Ausnahme:** Nextcloud ist über Tailscale Funnel öffentlich erreichbar, 2FA erzwungen
- Secrets in `~/.dahub-env`, `~/.da-agent-env` und `~/litellm/.env` (je chmod 600)
- Telegram-Token und Passwörter werden in Logs geschwärzt (da-agent)
- GitHub-Zugriff über Deploy Key `~/.ssh/da-hub-config` (SSH-Alias `github-dahub`), gilt nur für das eine Repo

---

## Dienste

| Dienst | Adresse | Bemerkung |
|---|---|---|
| Cockpit | `https://100.93.33.0:9090` | Server-Verwaltung |
| Portainer | `https://100.93.33.0:9443` | Nur noch Anzeige; Stacks 1, 2, 3, 5, 6 sind nach `~/stacks/` übernommen, Stack 4 (Watchtower) ist gestoppt (Einträge stehen noch, **nicht mehr darüber deployen**). Container selbst von Hand gestartet; Updates von Hand, `dahub-update.sh --pruefen` meldet Neubauten von `latest` |
| LiteLLM-Gateway | `http://100.93.33.0:4000` | v1.85.0 gepinnt, ohne Datenbank; Compose in `~/litellm/` |
| n8n | `https://da-hub.taile9dad7.ts.net:8443` | **v2.40.5** (30.09. per Freigabe-Knopf), Tailscale Serve → `localhost:5678`; Host-Port `5678` auf 0.0.0.0 |
| Nextcloud + MariaDB | `https://da-hub.taile9dad7.ts.net` | **v33.0.9** (30.09., begleitet), MariaDB 11.4.13; Tailscale Funnel → `127.0.0.1:8080`, 2FA; Host-Port `8080` auf 0.0.0.0 |
| ntfy | `:10000` | v2.28.0; Tailscale Serve `:10000` und `:8443/ntfy` → `localhost:9092` (Host-Port **9092**) |
| PostgreSQL + pgvector | `100.93.33.0:5432` | PostgreSQL 16.15, pgvector 0.8.6; Container `postgres-vector`, DB `knowledge`, User `dahub` |
| Ollama | `100.93.33.0:11434` | v0.33.3; Embedding-Modell `bge-m3` (1024 Dimensionen) |
| Docling | `100.93.33.0:5001` | docling-serve **v1.32.0** (29.09. kurz v1.34.0, zurückgenommen – siehe Änderungsprotokoll; v1.34.x in `dienste.conf` gesperrt); Dokument-Extraktion |
| Gotenberg | `:3000` | v8.36.0; HTML → PDF; Host-Port auf 0.0.0.0 |
| LibreOffice unoserver | `100.93.33.0:2004` | Image 3.19 (Neubau vom 20.09., eingespielt 29.09., Image `7dbd8fe5`); REST `POST /request` |
| Watchtower | – | **Gestoppt seit 28.09.2026** (`restart=no`, Container bleibt stehen). Ersetzt durch `dahub-update.sh` + Wochenbilanz. Rückweg: `docker update --restart=always watchtower && docker start watchtower` |
| **da-agent** | Telegram `@da_hub_bot` | systemd-Dienst, siehe unten |

Container mit `restart: always`.

### Herkunft der Container (Stand 27.09.2026)

| Quelle | Projektname (`name:`) | Container | Image (gepinnt) | Secrets |
|---|---|---|---|---|
| `~/stacks/gotenberg/` | `gotenberg` | gotenberg | `gotenberg/gotenberg:8.37.0` (seit 28.09. per `dahub-update.sh`) | – |
| `~/stacks/ntfy/` | `ntfy` | ntfy | `binwiederhier/ntfy:v2.28.0` | – |
| `~/stacks/wissensdatenbank/` | `wissensdatenbank` | postgres-vector, docling, ollama, libreoffice | `pgvector/pgvector:pg16`, `docling-serve:v1.32.0`, `ollama/ollama:0.33.3`, `libreoffice-unoserver:3.19` | `.env` (600): `PG_VECTOR_PASSWORD` |
| `~/stacks/n8n/` | `n8n` | n8n | `docker.n8n.io/n8nio/n8n:2.40.5` | `.env` (600): alle 9 Variablen |
| `~/litellm/` | `litellm` | litellm | `litellm:v1.85.0` | `.env` (600) |
| `~/stacks/nextcloude/` (seit 28.09.) | `nextcloude` (Tippfehler, so lassen) | nextcloud, nextcloud-db | `nextcloud:33.0.9`, `mariadb:11.4.13` | `.env` (600): 10 Variablen, pro Dienst unter `environment` als `${VAR}` |
| Portainer-Stack 4, **gestoppt 28.09.** | `watchover` (Tippfehler, so lassen) | watchtower | ungepinnt | Klartext in der Portainer-Datei |
| von Hand (`docker run`) | – | portainer | – | – |

- Portainer-Stacks liegen unter `/var/lib/docker/volumes/portainer_data/_data/compose/<Nr>/docker-compose.yml` (nur mit sudo lesbar). Keiner der Stacks bezieht Variablen aus der Portainer-DB; nur Stack 6 hatte eine `stack.env` (eine Variable)
- Die Compose-Dateien in `~/stacks/` sind identisch mit `compose/*-stack.yml` im Repo (Werte nur als `${VAR}`)
- Container, die nicht neu erstellt wurden, tragen im Label `working_dir` noch den alten Pfad (postgres-vector); das korrigiert sich beim nächsten Update
- Rückfall-Images: `dahub-rueckfall/libreoffice-unoserver:3.19-vor-uebernahme` (libreoffice vor dem Neubau), `dahub-rueckfall/mariadb:11.4.13-vor-uebernahme` (MariaDB vor dem Neubau desselben Tags); von `dahub-update.sh`: `dahub-rueckfall/<dienst>:vorher` (Stand 29.09. nach dem Rückfall: docling `09fc953c` = v1.34.0 – **nicht verwenden**, libreoffice `2bea150a`, gotenberg `87c16b9f`)
- Nextcloud-Sicherungen: `~/backup/` (700); Dump vor der Übernahme `nextcloud-20260928-1956.sql` + `.version.php`, Test-Dump `nextcloud-test-20260928-1846.sql` (je 132 MB, 600). Dump über den App-Benutzer: `mariadb-dump --single-transaction --no-tablespaces --quick` (3 s, 134 Tabellen, alle InnoDB)
- Testdatei für Funktionstests: `~/stacks/tests/test.pdf` (von Gotenberg erzeugt, enthält das Merkwort `Dahubtest4711`)

**Healthchecks** haben nur n8n (`wget …/healthz`, 60 s), Watchtower und Nextcloud. Es fehlen: litellm, postgres-vector, docling, ollama, libreoffice, nextcloud-db, portainer, ntfy, gotenberg. `check-container.sh` prüft ersatzweise Status und Port-Erreichbarkeit von aussen.

---

## LiteLLM-Gateway

- Seit 15.09.2026 als Compose-Stack: `~/litellm/docker-compose.yml` mit `env_file: .env`
- `~/litellm/.env` (chmod 600) enthält `ANTHROPIC_API_KEY` und `LITELLM_MASTER_KEY` → **Rotation = eine Zeile in dieser Datei**
- Modell-Konfiguration `~/litellm/config.yaml` (im Container `/app/config.yaml`), Sicherungen `config.yaml.bak-*`; Anthropic-Key über `os.environ/ANTHROPIC_API_KEY`, kein Klartext
- Aliase, alle getestet:

| Alias | Modell |
|---|---|
| `claude-opus` | `anthropic/claude-opus-5` |
| `claude-sonnet` | `anthropic/claude-sonnet-5` |
| `claude-haiku` | `anthropic/claude-haiku-4-5-20251001` |
| `da-agent` | `anthropic/claude-sonnet-5` |

- Master-Key am 15.09.2026 rotiert (vorher ein schwacher Standardwert), Format `sk-dahub-<32 hex>`; nachgezogen in `~/.dahub-env`, `~/.da-agent-env` und der n8n-Credential «LiteLLM Gateway»
- Abruf ohne Copy-Paste: `sed -n 's/^LITELLM_MASTER_KEY=//p' ~/litellm/.env`
- Ohne DB keine virtuellen Keys. Ein falscher Key liefert **HTTP 400** mit der irreführenden Meldung «No connected db», nicht 401
- Versionen 1.82.7 und 1.82.8 sind kompromittiert – nie verwenden
- Der Compose-Stack legt ein eigenes Netz `litellm_default` an; alle Zugriffe laufen über die Host-IP, nicht über Container-Namen
- Weitere Anbieter (OpenAI u. a.) als zusätzliche Einträge möglich, noch nicht eingerichtet

### Sonnet 5 / Opus 5 – Besonderheiten
- Adaptives Thinking standardmässig an (Default-Effort `high`)
- `temperature`, `top_p`, `top_k` mit Nicht-Standardwert → HTTP 400; manuelles Thinking-Budget → HTTP 400
- Geprüft am 10.09.: kein eigenes Skript und kein n8n-Workflow setzt diese Parameter; n8n nutzt nur `claude-haiku`

---

## Zugangsdaten (nur Namen/Orte)

- `~/.dahub-env`: Nextcloud-User `wissensbasis-bot`, Postgres, Docling, Ollama, `GATEWAY_KEY`, `TELEGRAM_TOKEN` (alter Bot) u. a. (als systemd-`EnvironmentFile`)
- `~/.da-agent-env`: Konfiguration des Agenten (27 Einträge), darunter `GATEWAY_KEY` und `TELEGRAM_TOKEN` (`@da_hub_bot`)
- `~/litellm/.env`: Anthropic-Key und LiteLLM-Master-Key
- Nextcloud-App-Passwörter (User `david`): eines für n8n (am 15.09.2026 erneuert), eines «da-agent»
- n8n-Owner-Login: `alvascheinaugustindavid@gmail.com`
- Mail-Versand: `automation@augustin.pro`, SMTP `smtp.servicehoster.ch:465` (SSL/TLS), in n8n eingerichtet
- IMAP `imap.servicehoster.ch:993` – noch nicht eingerichtet
- Sicherungen der Env-Dateien vom 15.09.2026: `~/.dahub-env.bak-*`, `~/.dahub-env.bak2-*`, `~/.da-agent-env.bak-*` (enthalten alte Keys, nach ein paar stabilen Tagen löschen)

---

## Wissensbasis (RAG-Pipeline)

| Komponente | Funktion |
|---|---|
| `scan_wissensbasis_simple.py` · `wissensbasis-scan.timer` (15 min) | ETag-Scanner, liest als `wissensbasis-bot`, nur `--root-path /Wissensbasis` |
| `process_jobs.py` · `wissensbasis-worker.timer` (5 min) | Worker: Docling, Embedding, pgvector; `--limit 100 --parallel 2`, `TimeoutStartSec=3600` |
| `frage.py` | Hybrid-Suche (Vektor + Volltext, RRF), `embed_query()`, `search(…, max_pro_dokument=2)` – **wird vom Agenten importiert, nicht entfernen** |
| `pffexport_to_nextcloud.py` | PST-Import (Mails als Dateien nach Nextcloud) |

- Tabellen: `documents`, `chunks`, `file_jobs`, `file_tracking`, `directory_etags`, `failed_documents`
- Pfadformat in `file_jobs`: `/remote.php/dav/files/wissensbasis-bot/Wissensbasis/…`
- `/Wissensbasis` gehört `david` und ist für `wissensbasis-bot` freigegeben; Unterordner werden automatisch erfasst
- Worker-Reihenfolge seit 11.09.: `ORDER BY (strpos(origin_path, '/Wissensbasis/da-agent/') > 0) DESC, id` → Agent-Dateien zuerst (Sicherung `~/process_jobs.py.bak-*`)
- Der Worker holt innerhalb eines Laufs wiederholt Jobs; Codeänderungen greifen erst ab dem nächsten Lauf
- **Stand 27.09.2026 (20:31):** pending 34'875 · processing 0 · done 106'122 · failed 1'072 · cancelled 106'603 · total 248'672 (15.09.: pending 103'019, done 38'449, failed 597)
- **Worker pausieren (seit 27.09.2026 erprobt):** Runtime-Drop-in `/run/systemd/system/wissensbasis-worker.service.d/pause.conf` mit `ConditionPathExists=!/run/dahub-worker-pause`. Existiert das Flag, überspringt systemd jeden Start. Stoppt keinen laufenden Lauf; das Drop-in liegt unter `/run` und verschwindet beim Neustart. Grundlage für das Wartungsflag in Phase 2
- Ein Timer-Stopp beendet den laufenden Worker nicht; ein Lauf, den der Timer kurz vor dem Stopp ausgelöst hat, läuft bis zu 3600 s weiter. Vor Eingriffen deshalb auf `ActiveState=inactive` **und** `processing = 0` warten
- Durchsatz: rund 10–15 Dokumente pro Stunde bei PDF/TIF mit OCR (`--parallel 2`). Die früher notierten 175/h galten für kleine Textdateien
- PST-Quellen (45 GB) in `/home/david/pst-source/`: `kgag-gesendet.pst`, `kgag-posteingang.pst`. Die Hockey-Club-Davos-PSTs (`temp1.pst`, `info@strozzis.ch.pst`) liegen **nicht** auf dem Server und müssen zuerst dorthin kopiert werden (`--source privat`)

### Fehlerbehandlung

- **Wiederholung ist eingebaut:** `process_jobs.py` setzt bei jedem Lauf alle `failed`-Jobs mit `attempts < 3` zurück auf `pending`. Was mit `attempts = 3` liegen bleibt, wird nie wieder angefasst – dort braucht es einen bewussten Eingriff
- `failed_documents` bleibt leer; der Fehlertext steht in `file_jobs.last_error`
- `file_jobs.status` hat eine CHECK-Constraint: nur `pending`, `processing`, `done`, `failed`, `cancelled`. Eigene Statuswerte werden abgewiesen
- **Docling-Timeout am 15.09.2026 von 120 auf 600 s angehoben** (`DOCLING_SERVE_MAX_SYNC_WAIT` im Portainer-Stack 6). Das Limit sitzt serverseitig in Docling, nicht in `process_jobs.py` – der dortige 600-s-Wert ist nur die Wartezeit des Clients
- Fehlerverteilung der 555 endgültig gescheiterten (Stand 15.09., alle vor der Anhebung):

| Fehler | Anzahl | Einschätzung |
|---|---|---|
| Docling 504 (Timeout) | 412 | durch die Anhebung voraussichtlich behoben |
| Verbindung zu Docling abgewiesen | 53 | entstand bei Container-Neustarts, kein Dateiproblem |
| Docling `failure`, `user_input` | 112 | echtes Problem: Format oder Datei defekt |
| Docling `failure`, `pipeline` | 6 | echtes Problem |
| «Nach mehreren Abbrüchen aufgegeben» | 5 | unklar |

- **Rückholen (offener Punkt, siehe unten):**

```sql
UPDATE file_jobs SET status='pending', attempts=0, last_error=NULL WHERE status='failed';
```

Ohne `attempts=0` stuft der Worker sie sofort wieder als erschöpft ein.

### Tägliche Fehlermeldung (seit 15.09.2026)

- `~/scripts/check-index-fehler.sh` · `index-fehler.timer` (täglich 08:00)
- Meldet nur endgültig gescheiterte Jobs (`attempts >= 3`), jede Datei genau einmal; Zustand in `~/.local/state/dahub-index-fehler.ids`
- Meldung enthält Anzahl neu, Gesamtzahl, drei Dateinamen, drei häufigste Fehlertypen und die Rückhol-Abfrage
- Versand über `notify.sh`; schlägt er fehl, werden die IDs nicht gemerkt und am Folgetag erneut versucht
- Beim Einrichten wurden die 555 bestehenden IDs vorab als gesehen eingetragen

### Diagnose (SSH-Session auf da-hub)

```bash
docker exec postgres-vector psql -U dahub -d knowledge \
 -c "SELECT status, count(*) FROM file_jobs GROUP BY 1 ORDER BY 2 DESC;" \
 -c "SELECT split_part(origin_path,'/',7) AS bereich, split_part(origin_path,'/',8) AS unterordner, count(*) AS offen FROM file_jobs WHERE status='pending' GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;" \
 -c "SELECT coalesce(substring(origin_path from '/(20[0-9]{2})/'),'ohne Jahr') AS jahr, count(*) AS offen FROM file_jobs WHERE status='pending' GROUP BY 1 ORDER BY 1 DESC;" \
 -c "SELECT count(*) FILTER (WHERE origin_path ILIKE '%vertr%') AS vertraege, count(*) FILTER (WHERE origin_path ~* '\.(pdf|docx?|xlsx?)$') AS dokumente, count(*) FILTER (WHERE origin_path ~* '\.(jpe?g|png|gif|heic)$') AS bilder, count(*) FILTER (WHERE origin_path ~* '\.(eml|msg|txt|htm?l?)$') AS mailtexte FROM file_jobs WHERE status='pending';"
```

**Achtung:** Der frühere Zähler `... WHERE processing_started_at > now() - interval '24 hours'` liefert immer 0 und ist kein Hinweis auf Stillstand – die Spalte wird nicht so gefüllt, wie die Abfrage annimmt. Fortschritt stattdessen über die Statusverteilung oder `journalctl -u wissensbasis-worker` prüfen.

---

## da-agent (in Betrieb seit 10.09.2026)

Persönlicher Always-on-Agent über Telegram. Kanal-Adapter-Architektur: WhatsApp später als zweiter Adapter.

- Bot `@da_hub_bot`, bedient ausschliesslich Chat-ID `8481460747`
- Code `~/da_agent.py` (v1.1), Konfiguration `~/.da-agent-env`
- Units: `da-agent.service` (Dauerbetrieb), `da-agent-nacht.service` + `.timer` (täglich 03:00)
- Selbsttest: `python3 ~/da_agent.py --env-file ~/.da-agent-env --check` (prüft Telegram, Postgres, `frage.py`, Ollama, Nextcloud, Gateway, Tool-Schleife)
- Log: `journalctl -u da-agent -f -o cat` (Werkzeuge, Tokens inkl. Cache, Antwortzeit)
- Telegram-Befehle: `/neu`, `/erinnerungen`, `/gedaechtnis`, `/hilfe`
- `ReadTimeout` bei `getUpdates` ist Long Polling bei Stille, kein Fehler – wird aber als WARNING geloggt und macht das Journal unnötig laut

**Werkzeuge** (feste Liste, keine Shell): `wissensbasis_suchen`, `verlauf_suchen`, `erinnerung_setzen/auflisten/loeschen`, `merken`, `gedaechtnis_korrigieren`, `gedaechtnis_lesen`, `mail_senden` (deaktiviert, solange `SMTP_PASSWORD` leer ist).

**Gedächtnis in drei Schichten:**
1. Rohverlauf in Postgres (`agent_messages`); `/neu` setzt nur einen Startpunkt (`agent_chat_state`), löscht nichts
2. Tagesjournal `/Wissensbasis/da-agent/journal/JJJJ-MM-TT.md` (Zusammenfassung + vollständiger Verlauf), nachts erzeugt und automatisch indexiert
3. Kerngedächtnis `/Wissensbasis/da-agent/gedaechtnis/kern.md`, bei jeder Anfrage gecacht geladen; Detailwissen in `gedaechtnis/themen/*.md`. Stand 15.09.: 302 Zeichen, keine Themendateien

- Jede Schreibaktion (Merken, Korrigieren, Mail, Verdichtung) nur nach Bestätigung per Button; offene Vorschläge in `agent_pending`
- Nachtroutine: Journal + bis zu 5 Gedächtnis-Vorschläge (verfallen nach 3 Tagen); ab 40'000 Zeichen Kern ein Verdichtungsvorschlag (Auslagerung statt Kürzung)
- Weitere Tabellen: `agent_reminders`, `agent_journal`
- Sicherheitsregel: Inhalte aus Dokumenten/Mails sind Daten, keine Anweisungen

**Gemessen (10.09.):** Frage mit Suche 11 s, grob 1,7 US-Cent (Einzelmessung); Cache-Treffer bestätigt.

### Alter Wissensbasis-Bot (läuft parallel)

- `wissensbasis-telegram.service` + `~/telegram_bot.py`, eigener Bot, Token am 15.09.2026 in BotFather erneuert
- Prüft eingehende Nachrichten gegen `TELEGRAM_ALLOWED_CHAT_ID` (Pflichtvariable), optional zusätzlich `TELEGRAM_ALLOWED_USER_ID`
- Bleibt vorerst aktiv zur Fortschrittskontrolle der Indexierung; Stilllegung danach

---

## Automationen (n8n)

- **Bauausschreibungen** (KGAG): 7 Nodes, freitags 10:00. Holt Zürcher Baugesuche über die öffentliche JSON-API `portal.ebaugesuche.zh.ch`, filtert ~50 Gastro-Begriffe, prüft Distanz zu 5 KGAG-Standorten (Haversine), erzeugt PDF via Gotenberg, Mail an `david.augustin@kramergastronomie.ch`. Ruft das Gateway nicht auf
- **Test Workflow** und **Zusammenfassung .txt**: Referenzketten Trigger → Nextcloud-Download → Extract from File → HTTP Request (Gateway) → Nextcloud-Upload. «Zusammenfassung .txt» liest `/remote.php/dav/files/david/test.txt` und schreibt `zusammenfassung.txt`
- **Email senden**: vorhanden (laut `n8n list:workflow` am 27.09.), Inhalt nicht dokumentiert
- Workflows laut `n8n list:workflow` am 27.09.2026: Zusammenfassung .txt, Bauausschreibung, Email senden, Test Workflow. **Der GBP Review Monitor ist dort nicht enthalten** – klären, ob gelöscht oder woanders
- Nextcloud-Credential «NextCloud account» nutzt nur «Zusammenfassung .txt» (inaktiv)
- **GBP Review Monitor**: pausiert, wartet auf Freigabe der Google-Business-Profile-API (GCP-Projekt `gbp-review-monitor`, Kramer-Gastro-Konto). Bringt eine eigene Anthropic-Bibliothek mit – prüfen, ob er das Gateway umgeht. Zusätzlich existiert `~/gbp-review-monitor/` mit eigener venv (Inhalt nicht dokumentiert)

### n8n – Credentials (Stand 15.09.2026)

| Name | Typ | Verwendung |
|---|---|---|
| LiteLLM Gateway | Header Auth | beide HTTP-Request-Nodes |
| NextCloud account | NextCloud API | Download/Upload |
| SMTP account | SMTP | 2 Nodes |
| NextCloud account 2 / 3 | NextCloud API | verwaist, keine Verknüpfung – löschen |

### n8n – Eigenheiten
1. Zuerst einen Trigger-Node setzen
2. Nextcloud-Credential: URL ohne WebDAV-Pfad; im File-Path `/remote.php/dav/files/david/DATEINAME`
3. `{{ … }}` wird nur im Expression-Modus ausgewertet
4. Verschachteltes JSON im HTTP-Node über `JSON.stringify({...})` bauen
5. Im Code-Node `this.helpers.httpRequest` verwenden
6. **Gateway-Zugriff über Credential, nicht über Header:** Authentication = Generic Credential Type → Header Auth → «LiteLLM Gateway». Eine zusätzliche `Authorization`-Zeile unter Headers überschreibt die Credential und muss gelöscht werden
7. **Allowed Domains** funktioniert nicht mit IP:Port – die Prüfung lehnt auch bei exakt gleicher Zeichenkette ab. Auf `All` stellen
8. Nextcloud-App-Passwörter können bei einem Nextcloud-Upgrade ungültig werden (401) – dann in Nextcloud unter Einstellungen → Sicherheit neu erzeugen
9. Dateien, die direkt ins Nextcloud-Volume gelegt werden, sind erst nach `occ files:scan` sichtbar. `--path="/david/files"` läuft rekursiv in die Wissensbasis (dauert lange) → einzelne Datei angeben oder `--shallow` verwenden
10. n8n 2.x meldet beim CLI-Aufruf eine Deprecation-Warnung zu `/home/node/.n8n/binaryData` (Umbenennung in v3, `N8N_MIGRATE_FS_STORAGE_PATH=true`) – noch nicht migriert

### n8n – Umgebung (geprüft 15.09.2026)

`N8N_PROTOCOL=https`, `N8N_SECURE_COOKIE=true`, `WEBHOOK_URL=https://da-hub.taile9dad7.ts.net:8443/`. Der frühere Kompromiss `N8N_SECURE_COOKIE=false` ist mit dem Umzug auf Tailscale Serve erledigt. **Webhook-Trigger sind damit einsatzbereit** – es existiert nur noch kein Workflow, der sie nutzt.

---

## Monitoring

- `~/scripts/check-container.sh`: 11 Container, Status + Port-Erreichbarkeit, 6 h Wiederholungssperre, Erholungsmeldung, Timer 5 min
- `~/scripts/smart-alert.sh`: SMART/NVMe
- `~/scripts/notify.sh`: ntfy mit Antwortprüfung, Log `~/.local/state/dahub-notify.log`; msmtp als Ersatzkanal (**nicht installiert**, `~/.msmtprc` fehlt). **Seit 28.09. direkt an `http://127.0.0.1:9092/dahub-alerts`** (vorher über `https://da-hub.taile9dad7.ts.net:10000`, scheiterte vom 21.09. bis 28.09., siehe offener Punkt K)
- `check-container.sh` schweigt seit 28.09., solange das Wartungsflag `~/.local/state/dahub-wartung` besteht; ist es älter als 3 h, meldet es das
- `nextcloud-cron.timer`: Nextcloud-Hintergrundjobs alle 5 min (`cron.php` im Container), Modus `cron` seit 28.09. (vorher AJAX)
- `~/stacks/bin/dahub-update.sh` (Phase 2): `--pruefen` zeigt fällige Updates; `--gruppe auto` bzw. `--dienst X [--version V]` aktualisiert mit Tests und Rückfall. Log `~/.local/state/dahub-update.log`. Karenzzeit 7 Tage, Linien in `dienste.conf`. Ollama-Test mit Kosinus-Vergleich zur Referenz `~/stacks/tests/ollama-referenz.json` (≥ 0.999)
  - Seit 28.09. (Phase 3): `--still` unterdrückt die Meldung bei Erfolg bzw. «nichts fällig» (Fehler werden weiter sofort gemeldet). Jeder `--gruppe`-Lauf schreibt `~/.local/state/dahub-update-ergebnis-<gruppe>` (zeit, epoch, rc, text)
  - `dienste.conf` hat eine 8. Spalte **meldelinie**: Bei Linie `-` meldet `--pruefen` passende Tags als «nur Meldung», spielt sie aber nie ein. Aufgenommen: `postgres-vector` (`^pg16$`, Test `t_pgvector`) und `portainer` (`^latest$`, Stack `-` = ohne Compose-Datei: Tag aus dem Container, Update wird verweigert, «von Hand»). n8n/LiteLLM meldet weiterhin `check-versionen.py`
  - `--simulieren` (seit 29.09.): ganzer Ablauf inkl. Flag, Warten auf den Worker, Rückfall-Tags und Tests, aber ohne pull/up/Compose-Änderung/Commit/ntfy – vor Änderungen am Skript immer zuerst so laufen lassen
  - `--dienst X --version <gleicher Tag>` zieht einen Neubau desselben Tags (ausser Nextcloud); bei unveränderter Image-ID geschieht nichts
- **`dahub-update.timer`** (seit 28.09.): sonntags 03:30, `--gruppe auto --still`, `Persistent=true`; der Service wartet vor dem Start, bis der Server 15 min läuft (nachgeholter Lauf nach Neustart), `TimeoutStartSec=3h`
- **`dahub-wochenbilanz.timer`** (seit 28.09.): montags 08:05, `~/stacks/bin/dahub-wochenbilanz.sh` → eine Meldung: Sonntagslauf (Totmann: fehlt er oder ist er älter als 48 h → Priorität high), Container laufend/ungesund (erwartet = `restart always|unless-stopped`), Indexierung pending/done und neu endgültig gescheitert seit der Vorwoche (Stand in `~/.local/state/dahub-wochenbilanz.stand`, Basis 28.09.: done 111'425, endgültig 1'107), verfügbare Freigabe-Updates. `--anzeigen` = nur ausgeben, nichts senden, nichts merken
- Wartungsflag `~/.local/state/dahub-wartung` pausiert Worker, Scan und Nextcloud-Cron über feste Drop-ins `dahub-wartung.conf` (`ConditionPathExists=!…`)
- `~/scripts/check-index-fehler.sh` + `index-fehler.timer`: täglich 08:00, meldet endgültig gescheiterte Indexierungen (siehe Wissensbasis)
- **Freigabe-Knopf (Phase 4, seit 30.09.):** `check-versionen.py` legt Angebote in `update_angebote` an (neueste Version ≥ 7 Tage, LiteLLM-Sperrliste, Docker-Tag vorhanden – n8n über Docker Hub `n8nio/n8n`, weil `docker.n8n.io` anonym mit HTTP 429 antwortet; Kurzfassung der Release Notes über das Gateway mit `claude-haiku`, Notes als Daten). Der da-agent schickt jedes Angebot mit «Einspielen» / «Später» (3 Tage) / «Überspringen», markiert ersetzte als «ersetzt durch …», meldet Ergebnisse, wertet `laeuft` > 3 h als Fehler. «Einspielen» startet die User-Unit `dahub-freigabe@<id>.service` (Linger aktiv) → `dahub-freigabe.sh` liest Dienst und Version aus der Datenbank, `--simulieren`, bei Grün echter Lauf; anderer Lauf aktiv → Angebot bleibt offen mit Hinweis. `check-versionen.py --nur n8n|litellm` begrenzt auf einen Dienst
- `check-versionen.py` + `versions-check.timer`: **wöchentlich**, montags 08:15; prüft die gepinnten Images n8n und LiteLLM auf neuere Versionen, mit Wiederholungssperre. Stand 15.09.: n8n 2.37.10 → 2.39.5, LiteLLM 1.85.0 → 1.101.0 verfügbar
- `unattended-upgrades` 2.12 installiert und aktiv (`APT::Periodic::Unattended-Upgrade "1"`)
- Docker-Healthchecks nur bei drei Containern (siehe oben)

---

## Infrastructure as Code

- Privates Repo `github.com/DavidAugustinAutomate/da-hub-config`, Zugriff über Deploy Key (SSH-Alias `github-dahub`), 37 Dateien
- Enthält: alle Compose-Stacks (n8n, Nextcloud, ntfy, Watchtower, Gotenberg, Verarbeitung, LiteLLM), Skripte (`da_agent.py`, `process_jobs.py`, `scan_wissensbasis_simple.py`, `frage.py`, `pffexport_to_nextcloud.py`, `telegram_bot.py`, `check-container.sh`, `notify.sh`, `smart-alert.sh`, `check-index-fehler.sh`, `check-versionen.py`), alle systemd-Units, Env-Vorlagen
- Passwörter in den Stack-Dateien durch `CHANGE_ME` ersetzt; die Werte wurden am 15.09.2026 per `git filter-repo` auch aus der Historie entfernt (Force-Push, Hashes haben sich geändert)
- **Nicht im Repo:** der von Hand gestartete Portainer-Container
- Muster für neue Dienste: eigenes Verzeichnis unter `~/stacks/<name>/` mit `name:` auf oberster Ebene, `restart: always`, nur Tailscale, Secrets in einer eigenen `.env` mit chmod 600, in der Compose-Datei nur `${VAR}`
- Commits 27.09.2026: `4c2e3a7` gotenberg, `c43d167` ntfy, `ec15767` Verarbeitung (wissensdatenbank), `b166123` n8n (Repo-Stand war vorher veraltet: 1.80.3, ohne Healthcheck). `main` folgt wieder `origin/main` (Upstream war seit dem `filter-repo` vom 15.09. nicht gesetzt)
- Commit 28.09.2026: `27bd1ff` Nextcloud (Repo-Stand vorher ohne Healthcheck, Tags `:33`/`:11.4`)
- Nur `compose/watchtower-stack.yml` ist noch nicht gegen die Portainer-Datei abgeglichen (Watchtower seit 28.09. gestoppt, Datei als stillgelegt markiert)
- Phase 3 (28.09.): `stacks/bin/dahub-wochenbilanz.sh`, `systemd/dahub-update.*`, `systemd/dahub-wochenbilanz.*`

---

## Änderungsprotokoll 28.09.2026 (Phase 3: Timer, Wochenbilanz, Watchtower)

1. **Entscheide David:** Montagsbilanz mit Totmann (statt Meldung des Sonntagslaufs), Watchtower stoppen und Container behalten, DNS über `nohook resolv.conf` (Variante a), vor dem ersten Timerlauf ein Handlauf `--gruppe auto`. Ergänzt: Bilanz zusätzlich mit Containern und Indexierung; pgvector und portainer als «freigabe» mit Linie `-` (nur Meldung); `Persistent=true` mit Startverzögerung
2. **`dahub-update.sh` erweitert** (`--still`, Ergebnisdatei, Meldelinie, Stack `-`, `t_pgvector`, `t_portainer`, postgres-vector pausiert den Worker) und **`dahub-wochenbilanz.sh`** neu; Mocktests (kein Lauf / ok / veraltet / rc=1) grün
3. **Watchtower gestoppt** (`docker update --restart=no` + `docker stop`), Container und Portainer-Eintrag 4 bleiben
4. **Erster Handlauf 21:52 abgebrochen**, ohne Eingriff (Flag gesetzt, sofort wieder entfernt, kein Container berührt): Die Prüfung `systemctl cat … | grep -qF` scheiterte unter `pipefail` an SIGPIPE, weil nach dem Treffer noch das alte Laufzeit-Drop-in `pause.conf` ausgegeben wurde – nachgestellt **182 von 200 falsch negativ**. Der gotenberg-Lauf um 21:23 kam nur zufällig durch. Gefährlicher war dieselbe Falle in der Warteschleife auf den Worker: Sie hätte einen laufenden Worker nie als aktiv erkannt (Mock 0/20) und docling mitten im Lauf neu gestartet
5. **Korrektur:** alle 10 Stellen `… | grep -q` / `… | head` in `dahub-update.sh` und `dahub-wochenbilanz.sh` auf Variable + Here-String bzw. `${var%%$'\n'*}` umgestellt; auf dem Server 200/200 für alle drei Drop-ins, alle 10 Funktionstests grün. Sicherungen: `~/tmp/p3-backup/` (vor Phase 3), `~/tmp/p3-backup2/` (vor der Korrektur)
6. **David (sudo):** `/run/systemd/system/wissensbasis-worker.service.d/pause.conf` entfernt, vier Units installiert, `daemon-reload`, beide Timer enabled; `NeedDaemonReload=no` geprüft. Erster Timerlauf So 04.10. 03:30, erste Bilanz Mo 05.10. 08:05
7. **Zweiter Handlauf** seit 22:01:38 (`--gruppe auto`, ohne `--still`, Ergebnis per ntfy): **brach um 23:11:49 ab** («Worker nach 70 min noch aktiv»), ohne Eingriff an Containern; zwei Meldungen (high + urgent). Ursache und Behebung siehe Änderungsprotokoll 29.09.

## Änderungsprotokoll 30.09.2026 (Phase 4: Freigabe-Knopf; n8n 2.40.5, Nextcloud 33.0.9)

1. **Linger** für `david` aktiviert (David, sudo): `Linger=yes`, `systemctl --user` läuft → User-Unit ohne sudo im Betrieb
2. **n8n-Datenbank:** SQLite (`database.sqlite` + WAL) im Volume `n8n_n8n_data`, dazu `config` mit dem Verschlüsselungsschlüssel. **Sicherung in `dahub-update.sh`:** n8n stoppen, Volume per Hilfscontainer (bisheriges n8n-Image, als root) nach `~/backup/n8n-<zeit>.tar.gz` (600), letzte 4 bleiben; bei rotem Test Volume aus der Sicherung zurück + altes Image. `--simulieren`: Probesicherung ohne Stopp, Wiederherstellung in ein Testvolume, `sqlite3 PRAGMA integrity_check` + Anzahl Workflows/Credentials, Testvolume wird entfernt
3. **Ergänzung b):** Angebot > 3 h `laeuft` → `fehler` mit Meldung; `flock` belegt → «Anderer Lauf aktiv, bitte später erneut», Angebot bleibt offen. **Ergänzung c):** Montagsbilanz meldet Hauptversionen der Gruppe auto als Hinweis ohne Knopf (erster Treffer: nextcloud-db 11.4.13 → 13.0.2)
4. **Tests:** 21 Python-Mocktests (Karenz, Sperrliste, übersprungen/ersetzt, Prompt-Grenze gegen Injection, fremde Chat-ID, doppeltes Tippen, alter Knopf, feste Befehlsliste des Unit-Starts), 9 Fälle für `dahub-freigabe.sh` (u. a. ID mit Shell-Zeichen), Probe `dahub-freigabe@999999` (unbekannt, nichts geändert)
5. **Eingespielt** (Commit `7194df1`, Sicherungen `*.bak-20260930-vor-phase4`), `da-agent` neu gestartet (David, sudo), Selbsttest «Alles bereit». Simulation `--gruppe auto` mit der neuen Fassung grün
6. **Erstes Angebot #1: n8n 2.37.10 → 2.40.5** (2.41.x noch in der Karenz). Knopf «Einspielen» 12:57 → Simulation grün (Probe ok, 4 Workflows, 3 Credentials) → echter Lauf mit Sicherung `n8n-20260930-125820.tar.gz` → Test grün 12:58:33, Commit `05105f2`. Geprüft: Image-ID = Tag, healthy, `/healthz` 200, 4 Workflows, 3 Credentials, 0× «Mismatching encryption keys», Angebot `erledigt`. Hinweis: 4× `X-Forwarded-For`-Warnung (Tailscale Serve; optional `N8N_PROXY_HOPS=1`). Kurzfassung hatte nur 2 statt 3–5 Stichpunkte – offen
7. **Nextcloud 33.0.9 begleitet** (am Sonntag fällig gewesen): Simulation grün, echter Lauf 13:14:27–13:15:01, Wartungsmodus 23 s, Dump `nextcloud-20260930-1314.sql` (101 MB, 134 Tabellen; 37 MB kleiner als am 28.09., weil der Cron 34,5 MB veraltete `oc_file_locks` und `oc_jobs` aufgeräumt hat), Tests grün (occ, WebDAV, Funnel), App-Passwörter 20 → 20, Commit `b0ebc3e`

## Änderungsprotokoll 29.09.2026 (Punkt G: Worker-Stufen 1–5)

Jede Stufe: Mocktests (`scripts/test_process_jobs.py`, zuletzt 40 Tests), Simulation mit `--simulieren --job-ids` (nur Jobs, die der Worker nie anfasst; Prüfung, dass Job-Zeilen und `documents` unverändert bleiben), Regression über alle Endungen, dann atomarer Austausch von `~/process_jobs.py` mit Sicherung.

| Stufe | Inhalt | Belege | Commit |
|---|---|---|---|
| 1 | Gesundheitsprüfung (docling, Ollama, Nextcloud) vor jeder Runde, docling-Probe mit Betriebsfeldern beim Start; abgewiesene Verbindung → Job ohne Versuch zurück (`attempts − 1`), Lauf endet mit rc 3; Abbruch mitten in der Anfrage zählt weiter (sonst Endlosschleife bei absturzauslösenden Dateien); `--simulieren` | Mock 15/15; docling-Port zu → Abbruch ohne Claim, Zeilen unverändert; Betrieb: 122 done, 0 Fehler | `6322e1a` |
| 2 | JPEG mit JFIF-Dichte 0 → 4 Bytes auf 96 dpi (Hash vom Original) | Simulation 18/18 (12 gescheiterte jpg OK) | `044fb07` |
| 3 | `NameError endung` behoben, NUL-Zeichen entfernt | NUL 3/3 OK; 7 xls zeigen jetzt den echten LibreOffice-Fehler | `451dba7` |
| 4 | CSV (Sniffer, utf-8/cp1252) und Excel (eigener xlsx-Leser, Standardbibliothek; xls über LibreOffice → xlsx) ohne docling; Fallback docling bei defektem xlsx | 57 gescheiterte Tabellen: 45 OK; Wortvergleich mit docling an 6 Dateien: 0 Textwörter verloren (nur Tabellen-Auffüllung und Zahlenformat) | `2f91b2d` |
| 5 | Weiche Frist 25 min (keine neuen Jobs), Zeitwächter pro Job (neuer Embedding-Batch nur bis 25 min Joblaufzeit → Job ≤ 30 min), Obergrenze 500'000 Zeichen; gekürzte Dateien: `documents.text_gekuerzt = true`, `text_zeichen_gesamt`, `file_tracking.index_status = 'gekuerzt'` | Messung 3,9 s/Chunk (Batch 32, unter Last); grosse xlsx 2,9 Mio. Zeichen → 285 Chunks in 16,1 min; 9 Tabellen würden gekürzt (bis 7,8 Mio. Zeichen) | `2f91b2d` |

- **Rechnung Stufe 5:** hartes Limit 60 min − 5 min Reserve = 55 = weiche Frist 25 + längster Job 30. Vor den Embeddings im ungünstigsten Fall 17 min (Download 120 s, LibreOffice 300 s, docling 600 s) – deshalb begrenzt der Zeitwächter die Gesamtzeit des Jobs, nicht nur die Zeichen
- **Anlass Stufe 5:** Die Läufe von 09:12:58 und 10:55:15 endeten durch `TimeoutStartSec` («start operation timed out», Journal bestätigt von David); in-flight-Jobs bekamen dabei einen Versuch angerechnet. Grosse Tabellen (bis 74 min Embeddings bei 2 Mio. Zeichen) waren die Ursache
- **Datenbank:** `ALTER TABLE documents ADD COLUMN text_gekuerzt boolean NOT NULL DEFAULT false, ADD COLUMN text_zeichen_gesamt integer` (29.09. 12:52, bei ruhendem Worker mit Wartungsflag). **Rückweg:** zuerst `cp ~/process_jobs.py.bak-20260929-vor-stufe4-5 ~/process_jobs.py`, danach `ALTER TABLE documents DROP COLUMN text_gekuerzt, DROP COLUMN text_zeichen_gesamt;` (die alte Fassung kennt die Spalten nicht)
- Sicherungen: `~/process_jobs.py.bak-20260929-vor-stufe1`, `-vor-stufe2`, `-vor-stufe3`, `-vor-stufe4-5`
- **Vollständiger Lauf mit allen fünf Stufen** 12:57:49–13:14:12: done +100 (Job-Limit), endgültig gescheitert +0, neue Fehlertexte 0, zurückgegeben 0
- **Gekürzte Dateien (Stufe c):** fest eingeplant nach Phase 4 – für alle `text_gekuerzt = true` in Teilen weiterindexieren (Fortschritt speichern, Fortsetzung über mehrere Läufe)
- Abfrage: `SELECT count(*) FROM documents WHERE text_gekuerzt;` bzw. `SELECT index_status, count(*) FROM file_tracking GROUP BY 1;`

## Änderungsprotokoll 29.09.2026 (Phase 3: Warteschleife, Simulation, erster echter Gruppenlauf)

1. **Ursache des Abbruchs 23:11 (gemessen):** `systemctl show -p ActiveState --value A B C` trennt die Units durch **Leerzeilen** (`activating\n\ninactive\n\ninactive`). Die Warteschleife `grep -qvxE 'inactive|failed'` wertete jede Leerzeile als «nicht ruhig» → das Skript hielt den Worker **immer** für aktiv. Der Fehler steckte schon in der ursprünglichen Fassung; die SIGPIPE-Korrektur vom 28.09. machte ihn von «meistens» zu «immer». Der Worker-Lauf von 21:26 endete spätestens 22:26 (`TimeoutStartSec=3600`), danach verhinderte das Flag jeden Start. Die Unit-Zeitstempel des Fensters waren überschrieben; `processing_started_at` wird nicht befüllt
2. **Korrektur `dahub-update.sh`** (Commit `7ab583a`): `aktive_units()` fragt jede Unit einzeln ab (leer/unbekannt = aktiv), Log nennt die aktiven Units alle 10 min; **ein** Abbruchweg `abbruch()` → genau eine Meldung mit Grund im Trap, Grund auch in der Ergebnisdatei (vorher zwei Meldungen); `commit_repo` überspringt den Commit, wenn die Compose-Datei unverändert ist (Neubau), statt «Commit fehlgeschlagen» zu melden
3. **Neuer Modus `--simulieren`:** echter Ablauf mit Sperre, Flag, Warten, Rückfall-Tags, Dry-Run auf einer Kopie der Compose-Datei (übersprungen, wenn das neue Image ohne pull nicht lokal ist), Tests gegen die laufenden Container – ohne pull, `compose up`, Compose-Änderung, Nextcloud-Wartungsmodus/Dump, Commit, Push und ntfy (Meldungen nur im Log). Ergebnis in `dahub-update-ergebnis-<gruppe>-simulation`, prüft am Ende, dass die Compose-Datei unverändert ist
4. **Mocktests** grün (Warten: ruhig/aktiv/leer/systemctl-Fehler; Abbruch: eine Meldung, Flag weg, Grund in Ergebnisdatei). **Simulation 1** rot (docling-Dry-Run: Image nicht lokal – Lücke der Simulation, behoben), **Simulation 2** grün: Flag entfernt, 6/6 Timer aktiv, 6/6 Compose-Dateien unverändert, Ergebnisdatei `auto` unverändert, 0 ntfy
5. **Echter Lauf `--gruppe auto`** 08:32–08:36 im Vordergrund: **docling v1.32.0 → v1.34.0** (`09fc953c`, Commit `7c22979` durch das Skript), **libreoffice 3.19 Neubau** (`7dbd8fe5`). Geprüft: Image-ID = Compose-Tag bei beiden, alle 10 Funktionstests grün, Flag entfernt, Sperre frei, 6/6 Timer aktiv, Nextcloud ohne Wartungsmodus, HEAD = origin/main, Compose-Datei = Repo, genau eine Meldung `[low]`
6. **Nebenbefund:** docling seit Erstellung 27.09. **3 Neustarts** (`RestartCount=3`, nicht OOM), letzter 29.09. 00:44; im Fenster danach ein ERROR aus `docling.backend.msexcel_backend` (Umwandlungsfehler, kein Absturz). Ursache der Neustarts nicht mehr feststellbar (Container beim Update neu erstellt, Logs weg)
7. **Regression docling v1.34.0:** Seit dem Update 08:35 scheiterte **jeder** Worker-Job mit `Docling-Fehler (404): {"detail":"Task result not found. Please wait for a completion status."}` (100 Jobs in den Läufen 08:40 und 08:45; nur die 2 Testumwandlungen gelangen). `t_docling` war grün, weil er eine einzelne Anfrage **ohne** die Felder des Workers schickte (`to_formats=md`, `do_ocr=true`, `ocr_lang=deu,eng`, `--parallel 2`). Gefunden bei der Auswertung zu Punkt G
8. **Rückfall** 08:46–08:48 mit `dahub-update.sh --dienst docling --version v1.32.0` (Freigabe David): Image-ID = Tag `5d1a649d`, Test grün, Flag entfernt, Timer aktiv, Commit `a142ee8`. Seither 0 ERROR im docling-Log
9. **100 Jobs zurückgesetzt** (Freigabe David, Grundsatz «kein Job geht verloren»): Auswahl über den Fehlertext (keine Zeitspalte für Fehlschläge vorhanden; der Text kam unter den 1'194 alten Fehlern nicht vor), alle hatten `attempts = 2`, **keiner erreichte 3**. `status='pending', attempts=0, last_error=NULL` in einer Transaktion mit Obergrenze
10. **`t_docling` neu** (Commit `b76a2db`): zwei Umwandlungen gleichzeitig mit denselben Feldern wie `process_jobs.py`, prüft HTTP 200, `status` success/partial_success und das Merkwort in `md_content`; gegen v1.32.0 3× grün. **docling fest auf v1.32.x** (Linie `^v1\.32\.\d+$`, Entscheid David, Commit `79c9778`); eine Folgeversion nur von Hand mit `--version` nach grünem `t_docling`
11. **Test belegt** mit befristetem Container `docling-test134` (v1.34.0, nur `127.0.0.1:5011`, eigenes tmpfs, danach entfernt): neuer `t_docling` gegen v1.34.0 2× **rot** (HTTP 404), gegen v1.32.0 grün; alter Einzeltest gegen v1.34.0 grün. Auslöser sind die **Felder** `to_formats`/`do_ocr`/`ocr_lang` – schon eine einzelne Anfrage damit liefert 404, Parallelität ist nicht nötig
12. **jpg-Klasse aufgeklärt** (Freigabe David; nur Kopfdaten gelesen, nichts gespeichert, keine Namen ausgegeben): 100 zufällige gescheiterte jpg sind formal einwandfrei (vollständig, baseline, RGB, > 100 px, 1–100 KB). Unterschied zu 60 erfolgreichen: **alle** gescheiterten haben im JFIF-Kopf Dichte-Einheit dpi mit **Wert 0** (dazu Adobe-APP14), bei keinem erfolgreichen. Gegenprobe gegen docling v1.32.0: 10/10 im Original «Could not load image», **10/10 OK nach Setzen der Dichte auf 96 dpi** (nur 4 Bytes, im Speicher), davon 6 mit Text

## Änderungsprotokoll 28.09.2026 (Phase 1: Nextcloud)

1. **Test-Dump** über den App-Benutzer `nextcloud` (hat `ALL PRIVILEGES` auf der DB `nextcloud`): 134 Tabellen, alle InnoDB, DB 716 MB, Dump 132 MB in 3 s
2. **Nextcloud übernommen** nach `~/stacks/nextcloude/` bei pausiertem Worker (Flag) und gestopptem Scan-Timer: `.env` per `stack-env-schreiben.py` aus der Portainer-Datei (10 Variablen, gemeinsame Namen in beiden Diensten mit gleichem Wert), Compose-Datei auf Basis der Portainer-Datei (Repo fehlte der Healthcheck), Config-Hash beider Dienste mit den bisherigen Tags identisch, Variablen pro Dienst unter `environment` als `${VAR}` (kein `env_file`). Gepinnt: `nextcloud:33.0.8` (= bisher laufend), `mariadb:11.4.13` (Neubau derselben Version, altes Image als Rückfall-Tag). Wartungsmodus an → Dump `nextcloud-20260928-1956.sql` + `version.php` → Neuerstellung beider Container → Wartungsmodus aus. Tests vorher und nachher grün: `occ status` (33.0.8, kein DB-Upgrade), WebDAV als `wissensbasis-bot` (207, gleiche Zugangsdaten wie der Scanner), Funnel `status.php`, App-Passwörter unverändert (22, inkl. `n8n-2026-09`), healthy. Commit `27bd1ff`
3. **Schlafende Laufzeit-Maske** `/run/systemd/system/wissensbasis-worker.service -> /dev/null` (seit 27.09. 20:31, von einem zweiten `mask --runtime`) gefunden und entfernt – sie wäre beim nächsten `daemon-reload` wirksam geworden. `pause.conf` war entgegen dem Anschein nie gelöscht (Verzeichnis-mtime unverändert)
4. Damit ist **Phase 1 abgeschlossen** bis auf Watchtower (Entscheid Phase 3)
5. **Nextcloud-Cron** (Punkt D): `nextcloud-cron.service/.timer` alle 5 min, Modus `cron` (der erste Lauf von `cron.php` hat von AJAX selbst umgestellt), `lastcron` läuft im 5-Minuten-Takt
6. **Phase 2 – `dahub-update.sh`** gebaut und eingerichtet (Commit `632f86d`): Versionssuche über Registry (Docker-Hub-API bzw. ghcr), Linie pro Dienst, Karenzzeit 7 Tage, ollama nur Patches 0.33.x, Rückfall-Tag `dahub-rueckfall/<dienst>:vorher`, automatischer Rückfall bei rotem Test, Nextcloud mit Wartungsmodus, Dump über App-Benutzer, `version.php`, Warten auf healthy vor `occ upgrade`, bei Fehler Wartungsmodus an + dringende Meldung. Feste Drop-ins `dahub-wartung.conf` für Worker/Scan, `check-container.sh` schweigt während des Flags. Review-Befunde eingearbeitet, Mocktests grün
7. **Erstes echtes Update:** `--dienst gotenberg` 8.36.0 → 8.37.0, Test grün, Commit `b9beeb8`
8. **ntfy-Meldungen seit 21.09. verloren** (DNS, Punkt K): 13 Meldungen, darunter eine Störung. `notify.sh` sendet jetzt direkt an `127.0.0.1:9092` (Commit `b147a34`), Testmeldung zugestellt. Das Repo enthielt noch die `notify.sh` von vor dem 09.09.

---

## Änderungsprotokoll 27.09.2026 (Phase 1: Umstellung auf reine Compose-Stacks)

Ziel laut `CLAUDE.md`: Unterhalt senken durch Vollautomatik + Freigabe-Knopf. Phase 1 = jeder Dienst unter `~/stacks/<name>/`.

1. **Bestandsaufnahme (1a):** Projektnamen, Volumes, Netze und Env-Namen aller Container erhoben. Portainer steuert keine Variablen aus seiner DB bei; nur Stack 6 hatte eine `stack.env`. Acht Container liefen auf Images, deren Tag lokal schon auf ein neueres Image zeigte (von Watchtower gezogen) – ein `up -d` ohne Pin wäre ein ungeplantes Update gewesen
2. **gotenberg** übernommen, auf 8.36.0 gepinnt (Image-ID = bisher laufend), Test: Health + Test-PDF
3. **ntfy** übernommen, von `:latest` auf v2.28.0 gepinnt (Image-ID geprüft), Test: Nachricht senden/empfangen auf Zufalls-Topic
4. **Verarbeitung (`wissensdatenbank`)** übernommen bei pausiertem Worker: docling auf v1.32.0 und ollama auf 0.33.3 gepinnt (Image-ID geprüft), **postgres-vector nicht neu gestartet** (Hash + Image gleich), libreoffice auf den Neubau von 3.19 (13.09.) aktualisiert, altes Image als Rückfall-Tag. Tests vor und nach der Übernahme: psql, Docling mit Test-PDF, `bge-m3`-Embedding (1024), LibreOffice Text → PDF. `file_jobs` vorher/nachher identisch
5. **n8n** übernommen: `.env` aus der Portainer-Datei per Skript erzeugt (Werte nie angezeigt), Werte im Container einzeln verglichen, Compose-Datei auf Basis der Portainer-Datei (Repo war veraltet), Config-Hash identisch. Einmalige Neuerstellung nötig (siehe Learnings). Tests: `/healthz`, healthy, kein «Mismatching encryption keys», 4 Workflows identisch
6. **Nextcloud** nur gemessen (Übernahme in eigener Sitzung, siehe offene Punkte)
7. Worker-Pause über Runtime-Drop-in erprobt, danach aufgehoben; Timer laufen seit 20:35 wieder. Ein vermuteter zweiter Auslöser des Workers existiert nicht – der Lauf von 20:15:28 stammte vom Timer kurz vor dessen Stopp
8. Claude-Code-Arbeitsordner: `.claude/settings.json` mit Freigaben nur für lesende Prüfungen im Scratchpad, Rückfrage für ssh/scp/rm/`sed -i`/git push, Sperre für alles mit `.ssh`, `.env`, `.dahub-env`. `CLAUDE.md` Regel 11: Server-Befehle als Skript bündeln, zeigen, mit einer Freigabe ausführen

---

## Änderungsprotokoll 15.09.2026 (Aufräum-Session)

1. **Telegram-Token des alten Wissensbasis-Bots** in BotFather widerrufen und erneuert, `~/.dahub-env` angepasst, Dienst neu gestartet, Antwort im Chat bestätigt
2. **LiteLLM-Master-Key rotiert.** Dabei festgestellt: Der Container stammte aus keiner Compose-Datei, sondern aus einem `docker run` von Hand. Umgestellt auf `~/litellm/docker-compose.yml` mit `env_file: .env`; `GATEWAY_KEY` in beiden Env-Dateien nachgezogen, Agent-Selbsttest vollständig grün. Beide n8n-Workflows auf die neue Header-Auth-Credential umgestellt (vorher war der Key dort hartcodiert, in den Credentials dagegen nicht)
3. **GitHub-Token** (`da-hub-server`, Scope `repo`, ohne Ablauf) durch einen Deploy Key ersetzt und widerrufen; Remote-URL umgestellt, Klartext-Token aus `.git/config` und `~/.bash_history` entfernt
4. **Klartext-Passwörter** aus `compose/nextcloud-stack.yml` und der Git-Historie entfernt (`git filter-repo`, Force-Push); Gegenprobe: null Treffer
5. **Repo vervollständigt:** vier fehlende Compose-Stacks, drei Skripte, drei Units – 23 → 33 Dateien
- Nebenbei: Nextcloud-App-Passwort für n8n war ungültig (401) und wurde erneut erzeugt; die im Workflow erwartete Datei `test.txt` fehlte und wurde neu angelegt
- Vorher am selben Tag von David: Nextcloud-Upgrade auf 33.0.8 abgeschlossen, n8n von 1.80.3 auf 2.37.10 aktualisiert

---

## Plan (Stand 28.09.2026)

1. **Phase 3 – erledigt am 28./29.09.:** `dahub-update.timer`, Wochenbilanz, Watchtower gestoppt, erster echter Gruppenlauf grün (siehe Änderungsprotokolle). **Offen:**
   - Punkt G (gescheiterte Indexierungen) – Auswertung 29.09. begonnen
   - ~~DNS (Punkt K)~~ erledigt 29.09.; Kontrolle nach der nächsten automatischen Lease-Erneuerung
   - Nach So 04.10. / Mo 05.10.: ersten Timerlauf und erste Wochenbilanz prüfen
2. **Phase 4 (Freigabe-Knopf) in Betrieb seit 30.09.** (siehe Änderungsprotokoll 30.09.). Früherer Stand: zurückgestellt; n8n und LiteLLM bis dahin von Hand mit `dahub-update.sh --dienst … --version …`
3. **Dann:** Punkt G (steigende Zahl endgültig gescheiterter Indexierungen) und anschliessend die Anwendungen (Roadmap «Agent richtig einsetzen»)

## Offene Punkte

### Aus Phase 1 (27.09.2026)

A. ~~Nextcloud-Übernahme (Stack 2)~~ **vollständig erledigt** (28.09. Übernahme; 30.09. n8n-Credential «NextCloud account» von David mit «Test» geprüft: in Ordnung; Funnel von aussen noch offen) (siehe Änderungsprotokoll 28.09.). Offen daraus nur noch: n8n-Credential «NextCloud account» einmal von Hand mit «Test» prüfen; Funnel einmal von aussen (Mobilnetz) aufrufen
B. **LAN-Erreichbarkeit der Ports 5678 (n8n), 8080 (nextcloud), 3000 (gotenberg) und 9092 (ntfy) prüfen.** Alle vier sind auf 0.0.0.0 gebunden; Docker umgeht ufw häufig. Tailscale Serve/Funnel zeigen auf `localhost`/`127.0.0.1`, eine Bindung auf `127.0.0.1` würde genügen
C. Nextcloud 33.0.9 verfügbar – erster Anwendungsfall für `dahub-update.sh` (Phase 2)
D. ~~Nextcloud-Hintergrundjobs auf Cron umstellen~~ **erledigt 28.09.2026** (`nextcloud-cron.timer`, Modus `cron`, siehe Änderungsprotokoll)
E. Nicht mehr benötigte Images (gotenberg `:8` = 8.37.0, docling/ollama `:latest`, `mariadb:11.4`, `nextcloud:33`) und die verwaisten Objekte Netz `6_default` sowie Volume `portainer` erst nach Abschluss von Phase 1 und nur mit Freigabe entfernen. Seit 28.09. zusätzlich: gestoppter Container `watchtower` + Image `nickfedor/watchtower`, sobald feststeht, dass er nicht mehr gebraucht wird
F. Portainer-Einträge 1, 2, 3, 5, 6: stehen lassen, nicht mehr darüber deployen (würden `:latest`/`:8` ziehen). Entfernen erst, wenn geklärt ist, ob dabei Container gestoppt werden
G. **Endgültig gescheiterte Indexierungen steigen stark:** laut täglicher Fehlermeldung **587 (20.09.) → 1'106 (28.09.) in 8 Tagen**, rund 65 pro Tag (`file_jobs.failed` 597 am 15.09., 1'072 am 27.09.). Blieb unbemerkt, weil die Meldungen seit 21.09. nicht zugestellt wurden (Punkt K). Die «neu»-Zahl der Meldung summiert sich seither auf (523 am 28.09.), weil die IDs nur nach erfolgreichem Versand gemerkt werden. Ursache (Fehlertypen) vordringlich untersuchen; mit dem Rückholen (Punkt 1) zusammen anschauen
   - **Grundsatz (David, 29.09.): Kein Job geht verloren.** Jede Fehlerklasse braucht einen Weg, auf dem die Datei am Ende doch indexiert wird. **Alle übrigen gescheiterten Jobs werden nach Abarbeitung des Rückstands erneut versucht** (`attempts=0`), jeweils nachdem der Weg für ihre Klasse umgesetzt ist
   - **Auswertung 29.09. (nur lesend), 1'194 endgültig gescheitert.** Knick am 22.09.: vorher 2–8 pro Tag, danach 45–101 – nicht zeitlich, sondern weil der Worker (arbeitet nach aufsteigender ID) den Bereich der Mail-Anhänge aus den PSTs erreichte (ID ≥ 80'000). Keine Zeitspalte für Fehlschläge; Trennung alt/neu über die Reihenfolge in `dahub-index-fehler.ids` (Zeilen 1–587 bis 21.09.)

| # | Klasse | Anzahl | Anteil | Endungen | Ursache | Weg zur Indexierung |
|---|---|---|---|---|---|---|
| 1 | Bild nicht ladbar (`Could not load image`) | 585 | 49,0 % | jpg | Alle aus dem Mail/PST-Bereich. **Belegt 29.09.:** JFIF-Dichte = 0 dpi (x und y), sonst einwandfreie JPEGs | Im Worker vor docling: bei JPEG mit JFIF-Dichte 0 die 4 Dichte-Bytes auf 96 setzen (Gegenprobe 10/10 OK). Danach zurücksetzen. Allgemein: Bild ohne erkannten Text trotzdem als `done` indexieren (Pfad, Mail-Kontext) |
| 2 | docling 504, Zeitüberschreitung (alt, 120 s) | 412 | 34,5 % | pdf 361, md 41, übrige 10 | Serverlimit vor 15.09. | Zurücksetzen – Limit ist seit 15.09. 600 s; Rest wie Klasse 5 |
| 3 | docling nicht erreichbar (`Connection refused`) | 93 | 7,8 % | md 52, pdf 29, übrige 12 | Ausfall von docling; 82 der neuen in **einem** zusammenhängenden ID-Block → ein Ausfall, den der Worker in drei Läufen zu 82 endgültigen Fehlern vervielfacht hat. Kein belegbarer Zusammenhang mit Excel (1 Excel-Job in der Nähe, Grundrate 1,3 %) | Zurücksetzen (Dateien sind in Ordnung). Vorbeugen: Worker prüft vor jedem Job `/health`; ist docling/LibreOffice/Ollama nicht erreichbar, bricht er den Lauf ab **ohne** `attempts` zu erhöhen |
| 4 | CSV nicht ladbar (`CsvDocumentBackend`) | 32 | 2,7 % | csv (Fehlerquote 51 %) | docling-CSV-Parser (Kodierung/Trennzeichen) | CSV nicht an docling: im Worker mit `csv.Sniffer` und Kodierungserkennung (utf-8/cp1252) lesen, als Text/Markdown-Tabelle indexieren |
| 5 | Read timeout 600 s | 27 | 2,3 % | pdf 26, xlsx 1 | Grosse PDFs (OCR) | Asynchrone docling-API (`/v1/convert/file/async` + Abfrage) mit langer Frist, oder PDF seitenweise in Teilen umwandeln |
| 6 | Worker-Abbruch («Nach mehreren Abbrüchen») | 9 | 0,8 % | xlsx 7, xls 2 | Job hing, bis der Worker-Lauf abgebrochen wurde | Excel nicht über docling: eigener Weg mit openpyxl/pandas (Blätter → Text), Grössenlimit pro Blatt |
| 7 | PDF defekt/nicht lesbar | 7 | 0,6 % | pdf | beschädigt oder ungewöhnlich aufgebaut | Mit qpdf/Ghostscript reparieren; sonst Seiten rastern (pdftoppm) und als Bilder per OCR |
| 8 | Bug `NameError: endung` | 7 | 0,6 % | xls | `process_jobs.py` Z. 253 (`convert_legacy`, Fehlerzweig nutzt `endung` statt `rohe_endung`) verdeckt den eigentlichen LibreOffice-Fehler | Variable korrigieren, zurücksetzen; danach je nach echtem Fehler Klasse 6 |
| 9 | docling-Validierung `SectionHeaderItem level` | 6 | 0,5 % | docx | docling-Fehler bei tiefen Überschriftenebenen | docx über LibreOffice → PDF, dann docling; alternativ neuere docling-Version (mit parallelem Test) |
| 10 | Verbindung abgebrochen (LibreOffice/Ollama/unbekannt) | 6 | 0,5 % | pdf 4, xls 1, md 1 | vorübergehend | Zurücksetzen; Vorbeugung wie Klasse 3 |
| 11 | Excel nicht zu öffnen | 4 | 0,3 % | xlsx | docling-Excel-Backend | wie Klasse 6 |
| 12 | NUL-Zeichen im Text | 3 | 0,3 % | pdf | Postgres-Text erlaubt kein `\x00` | `\x00` vor dem Speichern entfernen, zurücksetzen |
| 13 | Bild zu gross («decompression bomb») | 2 | 0,2 % | docx | Pillow-Grenze in docling | Bild vorher verkleinern bzw. docx über LibreOffice → PDF |
| 14 | übrige | 1 | 0,1 % | docx | – | einzeln anschauen |

   - **Stand nach den Worker-Stufen 1–5 (29.09.):** Wege umgesetzt für die Klassen 1 (jpg), 3 (Vorbeugung), 4 (CSV), 6/11 (Excel), 8 (NameError → echter Fehler sichtbar), 12 (NUL); Zurücksetzen dieser Klassen laut Grundsatz nach Abarbeitung des Rückstands. **12 Tabellen scheitern weiterhin** (Simulation, Kopfdaten geprüft):

| Anzahl | Endung | Befund | Weg zur Indexierung |
|---|---|---|---|
| 4 | xlsx (18–44 KB) | OOXML **verschlüsselt** (`EncryptedPackage`, Kennwortschutz) | Ohne Kennwort kein Text: als Dokument **ohne Text** indexieren (Pfad, Mail-Kontext) mit Markierung «verschlüsselt»; falls Kennwörter bekannt sind, später mit `msoffcrypto-tool` entschlüsseln |
| 5 | xls (je 8'994 KB, vermutlich dieselbe Datei mehrfach) | BIFF8-Workbook; LibreOffice bricht ab (exit 1) | xls direkt mit `xlrd` lesen (reines Python, als Benutzerpaket ohne sudo), ohne LibreOffice; Doppelte über `content_sha256` erkennen |
| 2 | xls (je 1'054 KB) | BIFF8-Workbook, evtl. Kennwortschutz (FILEPASS); LibreOffice nach 60 s abgebrochen | wie oben mit `xlrd`; meldet es «verschlüsselt» → wie die 4 xlsx ohne Text indexieren |
| 1 | xls (140 KB) | **kein Excel**, sondern eine MIME-Datei (Kopf «MIME», Excel-Webarchiv) | MIME im Worker zerlegen (Python `email`), HTML-Teil an docling oder als Text |

   - Reihenfolge-Vorschlag: sofort unkritisch zurücksetzbar sind 2, 3, 10 (511 Jobs) – aber erst nach Abarbeitung des Rückstands (Grundsatz oben); Code-Änderungen im Worker für 1, 3 (Vorbeugung), 4, 6/11, 8, 12; danach je Klasse zurücksetzen und die Quote prüfen
H. Viele alte Nextcloud-Sitzungen/App-Passwörter (Desktop-Clients, Browser, «n8n» vom 24.08.) aufräumen
I. **MariaDB-Root-Passwort klären:** `MYSQL_ROOT_PASSWORD` (32 Zeichen) wird für `root@localhost` abgewiesen. Klären, welches Passwort gilt bzw. ob Root per Socket/ohne Passwort eingerichtet ist; danach Variable und DB in Einklang bringen (`~/stacks/nextcloude/.env`). Dumps laufen bis dahin über den App-Benutzer
J. **`MARIADB_AUTO_UPGRADE` prüfen** (Review 28.09. zu `dahub-update.sh`, nur notiert): Ohne diese Variable führt das MariaDB-Image nach einem Versionssprung `mariadb-upgrade` nicht selbst aus. Für Patches innerhalb 11.4.x meist unkritisch; vor einem Wechsel der Linie (z. B. 11.8) klären, ob die Variable gesetzt oder `mariadb-upgrade` im Skript aufgerufen wird. Hängt mit Punkt I zusammen (Root-Zugang)
K. ~~DNS des Servers~~ **erledigt 29.09.2026 (David, sudo):** `nohook resolv.conf` in `/etc/dhcpcd.conf` (Sicherung `/etc/dhcpcd.conf.bak-20260929`); `resolv.conf` von Tailscale mit `100.100.100.100`; Tailnet-Name und `api.anthropic.com` lösen auf; `eno2` UP mit `192.168.1.198`, dhcpcd läuft; sha256 von `resolv.conf` vor und nach `dhcpcd -n eno2` identisch (`7af0f53c…`). `notify.sh` bleibt bewusst bei `127.0.0.1`. **Offen: nach der nächsten automatischen Lease-Erneuerung (`/var/lib/dhcpcd/eno2.lease`, mtime) prüfen, dass `resolv.conf` unverändert ist** (sha256 `7af0f53c…`, Kopfzeile nicht «Generated by dhcpcd»). Ursprünglicher Befund: **`dhcpcd` überschreibt `/etc/resolv.conf`** (Umsetzung in eigener Sitzung, sudo). Seit **20.09. 15:35** steht dort «Generated by dhcpcd from eno2.dhcp, eno2.dhcp6, eno2.ra» mit Router und Provider-DNS, ohne Tailscale-Resolver `100.100.100.100`. Folge: Der Server löst `da-hub.taile9dad7.ts.net` öffentlich auf (Funnel-IPv6 `2a00:dd80:20::…`), Port 10000/8443 sind dort nicht erreichbar → **alle ntfy-Meldungen vom 21.09. bis 28.09. gescheitert (13, HTTP 000)**, darunter eine Störungsmeldung. Behelf seit 28.09.: `notify.sh` sendet direkt an `http://127.0.0.1:9092`. Befund (nur lesend): `eno2` per ifupdown mit `dhcpcd` (Debian 13), Tailscale verwaltet DNS direkt über `resolv.conf` (kein `systemd-resolved`), MagicDNS selbst funktioniert (`dig @100.100.100.100` → `100.93.33.0`), **NetworkManager und ifupdown sind beide aktiv**. Tritt bei jeder Lease-Erneuerung wieder auf; ein Tailscale-Neustart repariert nur vorübergehend. Optionen: (a) `nohook resolv.conf` in `/etc/dhcpcd.conf`, (b) `systemd-resolved` einführen (Tailscale integriert sich dort sauber), (c) nur `/etc/hosts`-Eintrag für den eigenen Namen. Vorher mit sudo den Auslöser prüfen: `sudo journalctl --since '2026-09-20 15:30' --until '2026-09-20 15:40'`. `david` ist nicht in `adm`/`systemd-journal` und sieht das Systemjournal nicht
   - **Messung 28.09. (lesend):** dhcpcd 10.1.0 (Paket `dhcpcd-base`, von ifupdown für `eno2` gestartet, läuft seit dem Boot 09.09.) schreibt über den Hook `20-resolv.conf` (kein `resolvconf` installiert). Tailscale hat am 20.09. um **15:32** neu geschrieben (`/etc/resolv.pre-tailscale-backup.conf`), dhcpcd um **15:35** überschrieben. NetworkManager: `eno2` unmanaged (`[ifupdown] managed=false`), keine `/run/NetworkManager/resolv.conf` → schreibt nicht; effektive `dns=`-Einstellung noch mit sudo prüfen. `tailscale dns status`: Tailscale-DNS aktiv, Resolver Quad9, Split-DNS `ts.net`
   - **Entscheid 28.09.: Variante (a).** Ablauf (sudo, einzeln): `/etc/dhcpcd.conf` sichern → `nohook resolv.conf` anhängen → `dhcpcd -n eno2` (Konfiguration neu laden) → `tailscale set --accept-dns=false`, dann `=true` (Tailscale schreibt `resolv.conf` neu). Tests: `da-hub.taile9dad7.ts.net` → `100.93.33.0`, `api.anthropic.com` auflösbar. Danach Lease-Erneuerung (`dhcpcd -n eno2`) und prüfen, dass `resolv.conf` unverändert bleibt (sha256 vorher/nachher). Rückweg: Zeile entfernen, `dhcpcd -n eno2`. `notify.sh` bleibt bei `127.0.0.1`
M. **Portainer:** Neubau von `portainer/portainer-ce:latest` verfügbar (11,8 Tage alt, 28.09.). Nur bei Sicherheitslücken, von Hand (kein Compose; siehe Punkt 12 «Bisherige»)
L. **Repo-Stände der Skripte gegen den Server abgleichen:** `check-container.sh` und `notify.sh` lagen im Repo noch in der Fassung vor dem 09.09. (am 28.09. nachgeführt). Übrige Skripte in `scripts/` und Units in `systemd/` einmal mit `diff` gegen den Server prüfen

### Bisherige

1. **Stand 29.09.: aufgegangen in Punkt G** (alle 1'194 werden nach Abarbeitung des Rückstands erneut versucht). Ursprünglicher Text: **555 gescheiterte Indexierungen neu anstossen – nicht vergessen.** Erst wenn der Rückstand weitgehend abgearbeitet ist, damit sich das Ergebnis sauber zuordnen lässt. Erwartung: rund 465 gehen mit dem höheren Docling-Timeout durch, rund 120 bleiben als echte Problemfälle übrig, die dann einzeln anzuschauen sind.

```sql
UPDATE file_jobs SET status='pending', attempts=0, last_error=NULL WHERE status='failed';
```

2. **Passwörter in der Prozessliste** (zurückgestellt am 15.09.): `wissensbasis-worker.service` und `-scan.service` nutzen zwar `EnvironmentFile` und `${…}`-Platzhalter, übergeben Nextcloud- und Postgres-Passwort aber als Kommandozeilenargumente – dadurch in `ps aux` und `systemctl status` sichtbar. Beide Skripte kennen heute nur `argparse` (`required=True`), kein `os.environ`. **`frage.py` zeigt das Zielmuster** (`DAHUB_PG_PASSWORD`). Umbau plus Rotation beider Werte in eigener Sitzung
3. Alten Wissensbasis-Bot stilllegen, sobald die Indexierung durch ist: `wissensbasis-telegram.service` + `telegram_bot.py` nach `~/archiv/` (existiert noch nicht), danach Token in BotFather widerrufen. `frage.py` muss bleiben
4. Zwei verwaiste n8n-Credentials löschen («NextCloud account 2» und «3»)
5. LiteLLM-Upgrade (1.85.0 → 1.101.0 verfügbar, wird ab Mo 05.10. per Knopf angeboten), danach Datenbank und virtueller Key mit Budget für den Agenten. ~~n8n~~ erledigt 30.09. (2.40.5)
6. msmtp-Ersatzkanal für `notify.sh` einrichten (nicht installiert)
7. PST: Hockey-Club-Davos-PSTs auf den Server kopieren und importieren. Auslagern der 45 GB ist bei 631 GB frei nicht dringend
8. Weitere LLM-Anbieter ins Gateway (ursprünglich geplant: GPT, Gemini, Grok, Perplexity – je eigener API-Key mit Budget); Open WebUI als Chat-Oberfläche
8a. **Docker-Healthchecks** für die neun Container ohne (aus dem Härtungsblock vom 07.09., nie umgesetzt). Healthchecks mit `127.0.0.1`, nicht `localhost`
8b. **Webhook-Trigger + iPhone-Kurzbefehl** (besprochen am 07.09., nie gebaut). `WEBHOOK_URL` ist gesetzt, die Voraussetzungen stehen
9. Google-Ads-Automation: Architektur entworfen (Python-Wrapper, Kampagnen pausiert anlegen, Budget-Deckel, Freigabe via ntfy), nicht gebaut; Developer Token und OAuth2-Credentials fehlen
10. GBP Review Monitor: wartet auf Google-Freigabe (Stand 15.09. nicht erteilt). Danach Account-/Location-IDs, `config.yaml`, Baseline pro Standort, Wochenreports. Inhalt von `~/gbp-review-monitor/` dokumentieren
11. Baugesuche: monatliche Standort-Change-Detection ergänzen
12. Portainer-Container in eine Compose-Datei überführen und ins Repo
13. Env-Sicherungen vom 15.09. löschen, sobald der Betrieb stabil ist
14. `da_agent.py`: `ReadTimeout` bei `getUpdates` auf DEBUG statt WARNING
15. n8n: `binaryData` → `storage` migrieren vor v3

### Am 15.09.2026 geprüft und geschlossen (aus früheren Sitzungen)

- `N8N_SECURE_COOKIE=false` – hinfällig, steht auf `true`, n8n läuft über https
- Automatische Sicherheitsupdates – `unattended-upgrades` aktiv
- Postgres-Konnektivität nach Container-Neustart (offen seit 09.09.) – RestartCount 0, Container läuft seit 09.09. durch, nicht erneut aufgetreten
- Nextcloud: trusted domains, fehlende DB-Indizes nach dem Upgrade, Warnungen in der Übersicht – alle bereinigt
- ntfy-Benachrichtigungen, Git-Repo, SMART-Monitoring, Watchtower – umgesetzt

## Roadmap «Agent richtig einsetzen» – beschlossen: der Reihe nach

1. **Indexierung priorisieren** (Verträge, Mails der letzten 24 Monate zuerst) ← nächster Schritt
2. Dateien, Fotos und Sprachnachrichten im Chat (Whisper lokal)
3. Mails per Weiterleitung an `automation@augustin.pro` (IMAP)
4. Morgen-Briefing 07:00
5. Fristen-Radar über Verträge (zuerst Test mit 20 Verträgen)
6. n8n-Workflows als Werkzeuge (feste Webhook-Liste)
7. Mailversand freischalten (`SMTP_PASSWORD`)

Leitplanke: Nichts verlässt den Server ohne Bestätigung per Button.

---

## Projekt 2 (zurückgestellt): Resilienz

- Datenvolumen WD Red SA500 2 TB (SATA), Datenbank auf NVMe
- Backup: restic + AIO-Borg, zwei USB-SSDs im Wechsel (eine offsite), append-only, Test-Restore
- USV APC BX500MI + NUT für sauberes Herunterfahren

---

## Arbeitsweise & Learnings

- Ein Schritt nach dem anderen; bei jedem Befehl angeben, ob PowerShell (Laptop) oder SSH-Session (da-hub)
- Code als Dateien liefern; vor Übergabe `py_compile` und Tests mit Mocks
- Klein testen, dann skalieren; erst messen (`curl`, DB-Abfrage, Logs), dann diagnostizieren
- Python statt n8n für kritische Logik
- **Beim Kopieren aus dem Terminal die Eingabeaufforderung weglassen** – kopierte Ausgabezeilen führt Bash sonst als Befehle aus
- `scp` aus Downloads: Browser erzeugen `datei (1).py` → alte Datei vorher löschen, Inhalt nach Transfer prüfen; Windows-Pfade voll ausgeschrieben in Anführungszeichen
- `sudo -v` separat ausführen, nie mehrere sudo-Zeilen im Block
- **Env-Dateien:** `nano` verliert beim Einfügen gern Zeilenumbrüche → Werte danach mit Prüfskript kontrollieren (Längen, Leerzeichen, Vollständigkeit). Werte wenn möglich direkt aus Containern holen (`docker exec … printenv`)
- **Secrets wechseln:** neuen Wert per `read -r -s` einlesen (landet nicht in der History), mit `sed -i` in die Env-Datei schreiben, Länge per `awk` prüfen – nie den Wert selbst ausgeben
- **`grep -c` beweist nichts:** zählt nur, dass die Zeile existiert, nicht dass ein Wert drinsteht. Länge prüfen
- **Telegram-Token:** mit `getMe` prüfen, zu welchem Bot er gehört
- Docker-Healthchecks mit `127.0.0.1`, nicht `localhost`
- Watchtower sieht bei gepinnten Tags keine neuen Versionen → manuelle Reviews
- Sensibler Bereich: KGAG-Mails liegen auf dem privaten Server; jede weitere Anbindung von Geschäftsdaten bewusst entscheiden

### Learnings Phase 1 (27.09.2026)

- **Stack übernehmen ohne Überraschung:** (1) exakten Tag ziehen und Image-ID mit dem laufenden Container vergleichen, (2) `docker compose config --hash <svc>` der neuen Datei muss dem Label `com.docker.compose.config-hash` des laufenden Containers entsprechen, (3) Dry-Run darf kein Netz/Volume anlegen und keinen fremden Container betreffen, (4) Funktionstests vorher **und** nachher
- **Von Portainer erstellte Container werden von Compose 5.5.1 immer einmal neu erstellt**, auch bei gleichem Hash und Image: Portainer schrieb die Image-ID ins Label `com.docker.compose.image`, Compose erwartet dort einen anderen Digest. Container, die schon mit Compose 5.5.1 erstellt wurden (postgres-vector), bleiben unberührt
- **Derselbe Tag kann neu gebaut werden** (libreoffice 3.19, mariadb 11.4.13): Ein exakter Tag garantiert nicht dieselbe Image-ID. Vor der Übernahme dem laufenden Image einen lokalen Rückfall-Tag geben (`docker tag <id> dahub-rueckfall/...`)
- **Repo-Dateien können veraltet sein** (n8n: 1.80.3 statt 2.37.10, Healthcheck fehlte). Massgebend ist die Portainer-Datei bzw. der laufende Container; der Hash-Vergleich deckt Abweichungen auf
- **Config-Hash hängt an den aufgelösten Werten:** `${VAR}` aus `.env` ergibt denselben Hash wie der Klartext, wenn die Werte stimmen – eignet sich als Prüfung, dass ein Secret korrekt übertragen wurde, ohne es anzuzeigen
- **`.env` ohne Abtippen:** `sudo install -m 600 -o david -g david <quelle> <ziel>` (ohne `-D`, sonst legt root die Verzeichnisse an). Für Compose-Dateien mit Klartext: `sudo docker compose -f <datei> config --format json | python3 <skript>` schreibt die Werte als `KEY='wert'` (einfache Anführungszeichen, damit `$` nicht ausgewertet wird)
- **Stack 6 und alle Verarbeitungsdienste binden nur auf `100.93.33.0`** – Tests dort gegen die Tailscale-IP, nicht gegen `127.0.0.1`
- **Unter Git Bash auf Windows zählt `grep -c $'\r'` falsch** – CRLF mit `file` oder einem Byte-Vergleich (`wc -c` gegen `tr -d '\r' | wc -c`) prüfen
- **`echo … | grep -q` mit `pipefail`** kann einen Treffer verschlucken (SIGPIPE) – in Skripten `grep -q … <<<"$var"` verwenden
- **Nachtrag 28.09.:** Das gilt für **jeden** Empfänger, der die Pipe früh schliesst (`grep -q`, `head`, `sed …q`, `awk … exit`) und jeden Sender, der danach noch schreibt (`systemctl cat/show`, `docker`, `occ`). `systemctl cat | grep -q` war in 182 von 200 Fällen falsch. Bei Reviews gezielt nach `| grep -q` und `| head` suchen; erste Zeile per `${var%%$'\n'*}`
- **`systemctl show -p X --value A B C`** trennt die Units durch Leerzeilen – Zustände mehrerer Units nie gemeinsam per `grep -v` auswerten, sondern je Unit einzeln abfragen
- **Funktionstests müssen wie der echte Client arbeiten** (gleicher Endpunkt, gleiche Felder, gleiche Parallelität). Ein grüner Minimaltest hat am 29.09. eine docling-Version durchgelassen, an der jeder Worker-Job scheiterte. Nach einem Update ausserdem einen echten Lauf des Hauptnutzers prüfen (Worker: `done` steigt, keine neuen Fehlertexte)
- **Vor jedem echten Lauf simulieren** (`--simulieren`): Die Simulation fand den Dry-Run-Unterschied, der echte Lauf lief danach ohne Überraschung
- **Container-Logs** (libreoffice, docling, Worker) enthalten Dateinamen aus KGAG-Mails (Personen, Firmen) – nie ungefiltert ausgeben, nur Status-/Fehlerzeilen

---

## Betrieb & Kosten

- Fixkosten ~CHF 5–7/Monat (Strom, amortisierter USV-Akku); Software und Tailscale gratis
- Variable Kosten: Anthropic-API (pay-as-you-go). Ausgabenlimit: Console → Settings → Limits → «Spend limits»; Verbrauch unter Usage/Cost
- Abo deckt interaktives Arbeiten, API die Automationen – bewusst getrennt
- Sonnet 5: $2 / $10 pro Mio. Tokens (Input/Output), Cache-Lesen $0.20
