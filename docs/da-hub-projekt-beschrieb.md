# Projekt-Beschrieb: Automatisierungshub «da-hub»

*Kontextdokument für künftige Chats. Stand: 28.09.2026. Ersetzt den Beschrieb vom 15.09.2026.*
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
| Portainer | `https://100.93.33.0:9443` | Nur noch Anzeige; Stacks 1, 2, 3, 5, 6 sind nach `~/stacks/` übernommen (nur Stack 4 Watchtower noch nicht) (Einträge stehen noch, **nicht mehr darüber deployen**). Container selbst von Hand gestartet |
| LiteLLM-Gateway | `http://100.93.33.0:4000` | v1.85.0 gepinnt, ohne Datenbank; Compose in `~/litellm/` |
| n8n | `https://da-hub.taile9dad7.ts.net:8443` | v2.37.10, Tailscale Serve → `localhost:5678`; Host-Port `5678` auf 0.0.0.0 |
| Nextcloud + MariaDB | `https://da-hub.taile9dad7.ts.net` | v33.0.8 (33.0.9 verfügbar), MariaDB 11.4.13; Tailscale Funnel → `127.0.0.1:8080`, 2FA; Host-Port `8080` auf 0.0.0.0 |
| ntfy | `:10000` | v2.28.0; Tailscale Serve `:10000` und `:8443/ntfy` → `localhost:9092` (Host-Port **9092**) |
| PostgreSQL + pgvector | `100.93.33.0:5432` | PostgreSQL 16.15, pgvector 0.8.6; Container `postgres-vector`, DB `knowledge`, User `dahub` |
| Ollama | `100.93.33.0:11434` | v0.33.3; Embedding-Modell `bge-m3` (1024 Dimensionen) |
| Docling | `100.93.33.0:5001` | docling-serve v1.32.0; Dokument-Extraktion |
| Gotenberg | `:3000` | v8.36.0; HTML → PDF; Host-Port auf 0.0.0.0 |
| LibreOffice unoserver | `100.93.33.0:2004` | Image 3.19 (Neubau 13.09.), LibreOffice 7.6.7.2; REST `POST /request` |
| Watchtower | – | Fork `nickfedor`, nur Meldung, täglich 08:00 (`containrrr` ist verwaist – nicht verwenden) |
| **da-agent** | Telegram `@da_hub_bot` | systemd-Dienst, siehe unten |

Container mit `restart: always`.

### Herkunft der Container (Stand 27.09.2026)

| Quelle | Projektname (`name:`) | Container | Image (gepinnt) | Secrets |
|---|---|---|---|---|
| `~/stacks/gotenberg/` | `gotenberg` | gotenberg | `gotenberg/gotenberg:8.37.0` (seit 28.09. per `dahub-update.sh`) | – |
| `~/stacks/ntfy/` | `ntfy` | ntfy | `binwiederhier/ntfy:v2.28.0` | – |
| `~/stacks/wissensdatenbank/` | `wissensdatenbank` | postgres-vector, docling, ollama, libreoffice | `pgvector/pgvector:pg16`, `docling-serve:v1.32.0`, `ollama/ollama:0.33.3`, `libreoffice-unoserver:3.19` | `.env` (600): `PG_VECTOR_PASSWORD` |
| `~/stacks/n8n/` | `n8n` | n8n | `docker.n8n.io/n8nio/n8n:2.37.10` | `.env` (600): alle 9 Variablen |
| `~/litellm/` | `litellm` | litellm | `litellm:v1.85.0` | `.env` (600) |
| `~/stacks/nextcloude/` (seit 28.09.) | `nextcloude` (Tippfehler, so lassen) | nextcloud, nextcloud-db | `nextcloud:33.0.8`, `mariadb:11.4.13` | `.env` (600): 10 Variablen, pro Dienst unter `environment` als `${VAR}` |
| Portainer-Stack 4 (Entscheid Phase 3) | `watchover` (Tippfehler, so lassen) | watchtower | ungepinnt | Klartext in der Portainer-Datei |
| von Hand (`docker run`) | – | portainer | – | – |

- Portainer-Stacks liegen unter `/var/lib/docker/volumes/portainer_data/_data/compose/<Nr>/docker-compose.yml` (nur mit sudo lesbar). Keiner der Stacks bezieht Variablen aus der Portainer-DB; nur Stack 6 hatte eine `stack.env` (eine Variable)
- Die Compose-Dateien in `~/stacks/` sind identisch mit `compose/*-stack.yml` im Repo (Werte nur als `${VAR}`)
- Container, die nicht neu erstellt wurden, tragen im Label `working_dir` noch den alten Pfad (postgres-vector); das korrigiert sich beim nächsten Update
- Rückfall-Images: `dahub-rueckfall/libreoffice-unoserver:3.19-vor-uebernahme` (libreoffice vor dem Neubau), `dahub-rueckfall/mariadb:11.4.13-vor-uebernahme` (MariaDB vor dem Neubau desselben Tags)
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
- Wartungsflag `~/.local/state/dahub-wartung` pausiert Worker, Scan und Nextcloud-Cron über feste Drop-ins `dahub-wartung.conf` (`ConditionPathExists=!…`)
- `~/scripts/check-index-fehler.sh` + `index-fehler.timer`: täglich 08:00, meldet endgültig gescheiterte Indexierungen (siehe Wissensbasis)
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
- Nur `compose/watchtower-stack.yml` ist noch nicht gegen die Portainer-Datei abgeglichen

---

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

## Offene Punkte

### Aus Phase 1 (27.09.2026)

A. ~~Nextcloud-Übernahme (Stack 2)~~ **erledigt 28.09.2026 19:56** (siehe Änderungsprotokoll 28.09.). Offen daraus nur noch: n8n-Credential «NextCloud account» einmal von Hand mit «Test» prüfen; Funnel einmal von aussen (Mobilnetz) aufrufen
B. **LAN-Erreichbarkeit der Ports 5678 (n8n), 8080 (nextcloud), 3000 (gotenberg) und 9092 (ntfy) prüfen.** Alle vier sind auf 0.0.0.0 gebunden; Docker umgeht ufw häufig. Tailscale Serve/Funnel zeigen auf `localhost`/`127.0.0.1`, eine Bindung auf `127.0.0.1` würde genügen
C. Nextcloud 33.0.9 verfügbar – erster Anwendungsfall für `dahub-update.sh` (Phase 2)
D. ~~Nextcloud-Hintergrundjobs auf Cron umstellen~~ **erledigt 28.09.2026** (`nextcloud-cron.timer`, Modus `cron`, siehe Änderungsprotokoll)
E. Nicht mehr benötigte Images (gotenberg `:8` = 8.37.0, docling/ollama `:latest`, `mariadb:11.4`, `nextcloud:33`) und die verwaisten Objekte Netz `6_default` sowie Volume `portainer` erst nach Abschluss von Phase 1 und nur mit Freigabe entfernen
F. Portainer-Einträge 1, 2, 3, 5, 6: stehen lassen, nicht mehr darüber deployen (würden `:latest`/`:8` ziehen). Entfernen erst, wenn geklärt ist, ob dabei Container gestoppt werden
G. **Endgültig gescheiterte Indexierungen steigen stark:** laut täglicher Fehlermeldung **587 (20.09.) → 1'106 (28.09.) in 8 Tagen**, rund 65 pro Tag (`file_jobs.failed` 597 am 15.09., 1'072 am 27.09.). Blieb unbemerkt, weil die Meldungen seit 21.09. nicht zugestellt wurden (Punkt K). Die «neu»-Zahl der Meldung summiert sich seither auf (523 am 28.09.), weil die IDs nur nach erfolgreichem Versand gemerkt werden. Ursache (Fehlertypen) vordringlich untersuchen; mit dem Rückholen (Punkt 1) zusammen anschauen
H. Viele alte Nextcloud-Sitzungen/App-Passwörter (Desktop-Clients, Browser, «n8n» vom 24.08.) aufräumen
I. **MariaDB-Root-Passwort klären:** `MYSQL_ROOT_PASSWORD` (32 Zeichen) wird für `root@localhost` abgewiesen. Klären, welches Passwort gilt bzw. ob Root per Socket/ohne Passwort eingerichtet ist; danach Variable und DB in Einklang bringen (`~/stacks/nextcloude/.env`). Dumps laufen bis dahin über den App-Benutzer
J. **`MARIADB_AUTO_UPGRADE` prüfen** (Review 28.09. zu `dahub-update.sh`, nur notiert): Ohne diese Variable führt das MariaDB-Image nach einem Versionssprung `mariadb-upgrade` nicht selbst aus. Für Patches innerhalb 11.4.x meist unkritisch; vor einem Wechsel der Linie (z. B. 11.8) klären, ob die Variable gesetzt oder `mariadb-upgrade` im Skript aufgerufen wird. Hängt mit Punkt I zusammen (Root-Zugang)
K. **DNS des Servers: `dhcpcd` überschreibt `/etc/resolv.conf`** (Umsetzung in eigener Sitzung, sudo). Seit **20.09. 15:35** steht dort «Generated by dhcpcd from eno2.dhcp, eno2.dhcp6, eno2.ra» mit Router und Provider-DNS, ohne Tailscale-Resolver `100.100.100.100`. Folge: Der Server löst `da-hub.taile9dad7.ts.net` öffentlich auf (Funnel-IPv6 `2a00:dd80:20::…`), Port 10000/8443 sind dort nicht erreichbar → **alle ntfy-Meldungen vom 21.09. bis 28.09. gescheitert (13, HTTP 000)**, darunter eine Störungsmeldung. Behelf seit 28.09.: `notify.sh` sendet direkt an `http://127.0.0.1:9092`. Befund (nur lesend): `eno2` per ifupdown mit `dhcpcd` (Debian 13), Tailscale verwaltet DNS direkt über `resolv.conf` (kein `systemd-resolved`), MagicDNS selbst funktioniert (`dig @100.100.100.100` → `100.93.33.0`), **NetworkManager und ifupdown sind beide aktiv**. Tritt bei jeder Lease-Erneuerung wieder auf; ein Tailscale-Neustart repariert nur vorübergehend. Optionen: (a) `nohook resolv.conf` in `/etc/dhcpcd.conf`, (b) `systemd-resolved` einführen (Tailscale integriert sich dort sauber), (c) nur `/etc/hosts`-Eintrag für den eigenen Namen. Vorher mit sudo den Auslöser prüfen: `sudo journalctl --since '2026-09-20 15:30' --until '2026-09-20 15:40'`. `david` ist nicht in `adm`/`systemd-journal` und sieht das Systemjournal nicht
L. **Repo-Stände der Skripte gegen den Server abgleichen:** `check-container.sh` und `notify.sh` lagen im Repo noch in der Fassung vor dem 09.09. (am 28.09. nachgeführt). Übrige Skripte in `scripts/` und Units in `systemd/` einmal mit `diff` gegen den Server prüfen

### Bisherige

1. **555 gescheiterte Indexierungen neu anstossen – nicht vergessen.** Erst wenn der Rückstand weitgehend abgearbeitet ist, damit sich das Ergebnis sauber zuordnen lässt. Erwartung: rund 465 gehen mit dem höheren Docling-Timeout durch, rund 120 bleiben als echte Problemfälle übrig, die dann einzeln anzuschauen sind.

```sql
UPDATE file_jobs SET status='pending', attempts=0, last_error=NULL WHERE status='failed';
```

2. **Passwörter in der Prozessliste** (zurückgestellt am 15.09.): `wissensbasis-worker.service` und `-scan.service` nutzen zwar `EnvironmentFile` und `${…}`-Platzhalter, übergeben Nextcloud- und Postgres-Passwort aber als Kommandozeilenargumente – dadurch in `ps aux` und `systemctl status` sichtbar. Beide Skripte kennen heute nur `argparse` (`required=True`), kein `os.environ`. **`frage.py` zeigt das Zielmuster** (`DAHUB_PG_PASSWORD`). Umbau plus Rotation beider Werte in eigener Sitzung
3. Alten Wissensbasis-Bot stilllegen, sobald die Indexierung durch ist: `wissensbasis-telegram.service` + `telegram_bot.py` nach `~/archiv/` (existiert noch nicht), danach Token in BotFather widerrufen. `frage.py` muss bleiben
4. Zwei verwaiste n8n-Credentials löschen («NextCloud account 2» und «3»)
5. LiteLLM-Upgrade (1.85.0 → 1.101.0 verfügbar), danach Datenbank und virtueller Key mit Budget für den Agenten. Ebenso n8n 2.37.10 → 2.39.5
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

---

## Betrieb & Kosten

- Fixkosten ~CHF 5–7/Monat (Strom, amortisierter USV-Akku); Software und Tailscale gratis
- Variable Kosten: Anthropic-API (pay-as-you-go). Ausgabenlimit: Console → Settings → Limits → «Spend limits»; Verbrauch unter Usage/Cost
- Abo deckt interaktives Arbeiten, API die Automationen – bewusst getrennt
- Sonnet 5: $2 / $10 pro Mio. Tokens (Input/Output), Cache-Lesen $0.20
