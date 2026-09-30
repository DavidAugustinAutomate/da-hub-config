# Google-Ads-Automation (KGAG) – `~/stacks/google-ads`

Teilprojekt auf da-hub. Etappe 1a: Python-Umgebung, einmalige OAuth-Anmeldung, erste reine Leseabfrage.

## Zugang

- Seit 09.09.2026 keine Developer Tokens mehr; die Zugangsstufe hängt am Google-Cloud-Projekt des OAuth-Clients
  (`kgag-google-ads`, Stufe **Explorer**: produktive Konten, **2'880 Operationen/Tag**; Keyword Planner, Planungs-,
  Abrechnungs- und Benutzerverwaltungsdienste gesperrt). Kein Verwaltungskonto (MCC), kein `login_customer_id`.
- Konto: Kunden-ID `5777888366`. Anmeldung mit dem Konto, das im Ads-Konto Administratorzugriff hat.
- Bibliothek `google-ads==33.0.0` (Google Ads API **v25**), alle Abhängigkeiten in `requirements.lock.txt`.

## Dateien

| Datei | Inhalt | Repo |
|---|---|---|
| `ads_common.py` | gemeinsamer Weg zum Client (liest `oauth-client.json` + `.env`, prüft Rechte 600, kein Developer Token, kein `login_customer_id`, `use_proto_plus`), Fehlertexte ohne Tokens | ja |
| `ads_auth.py` | einmalige Anmeldung (Installed-App-Flow, `127.0.0.1:8765`, `access_type=offline`, `prompt=consent`), schreibt `GOOGLE_ADS_REFRESH_TOKEN` in `.env` | ja |
| `ads_check.py` | Leseprüfung: Konto (Name, Währung, Zeitzone), Kampagnen nach Status und als Liste | ja |
| `test_ads.py` | Mocktests (Konfiguration, Rechte, leeres Token, Fehlerausgabe, Client ohne Developer Token, Ausgabe) | ja |
| `requirements.txt` / `requirements.lock.txt` | gepinnte Version / vollständiger Stand des venv | ja |
| `env.vorlage` | Vorlage für `.env` ohne Werte | ja |
| `oauth-client.json` | OAuth-Client (Desktop-App), 600 | **nein** |
| `.env` | Refresh-Token, 600 | **nein** |
| `venv/` | Python-Umgebung | **nein** |

## Anmeldung (einmalig, bei Widerruf erneut)

1. PowerShell (Laptop): `ssh -N -L 8765:127.0.0.1:8765 david@100.93.33.0` – Tunnel offen lassen
2. SSH-Session da-hub: `~/stacks/google-ads/venv/bin/python ~/stacks/google-ads/ads_auth.py`
3. Browser (Laptop): ausgegebene Adresse öffnen, anmelden, zustimmen → Weiterleitung auf `127.0.0.1:8765` durch den Tunnel
4. Tunnel mit Ctrl+C schliessen. Prüfung nur über Länge: `awk -F= '{print $1, length($2)}' ~/stacks/google-ads/.env`

Variante `--iphone` (Anmeldung in Safari, z. B. wenn der Passkey nur auf dem iPhone liegt):
`~/stacks/google-ads/venv/bin/python ~/stacks/google-ads/ads_auth.py --iphone` – Anmeldelink kommt per ntfy
(`dahub-alerts`, direkt gesendet, nicht über `notify.sh`, damit nichts protokolliert wird). Nach der Zustimmung die
Adresse `http://127.0.0.1:8765/?state=…&code=…` aus der Safari-Adresszeile kopieren und über «2 Rückweg» in der
ntfy-Web-App auf dem Einmal-Topic `ga-rueck-<zufall>` senden (nur Tailnet). Gleiche `redirect_uri`, PKCE, state-Prüfung,
Zeitlimit 10 Minuten; Code und Adresse werden nie ausgegeben.

Stand 30.09.2026: Anmeldung noch nicht erfolgt – neue Passkeys von `kramergastronomie@gmail.com` wirken erst nach
Googles Wartezeit (bis 07.10.2026), danach Tunnel-Modus in Chrome.

## Leseprüfung

`~/stacks/google-ads/venv/bin/python ~/stacks/google-ads/ads_check.py`

## Vorgaben für spätere Etappen (verbindlich, noch nicht gebaut)

- **Kampagnen nur im Status `PAUSED` anlegen.** Aktivieren und jede Änderung nur nach Freigabe per Knopf im da-agent.
- **Harter Budget-Deckel im Wrapper** – Aufrufe, die ihn überschreiten würden, werden vor dem Senden abgewiesen.
- **Markenregel:** Kramer Gastronomie darf in der Werbung nicht wahrnehmbar sein. Anzeigentexte, Unternehmensnamen
  und Ziel-URLs mit «Kramer» (jede Schreibweise) oder `kramergastronomie.ch` werden abgewiesen; Ziel-URLs sind immer
  die Website des jeweiligen Betriebs.
- **Quote Explorer: 2'880 Operationen/Tag** beachten (zählen, vor Erreichen stoppen).
