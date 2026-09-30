#!/usr/bin/env python3
"""ads_auth.py – einmalige OAuth-Anmeldung fuer Google Ads (Installed-App-Flow).

Modus Tunnel (Standard, unveraendert):
  1. PowerShell (Laptop):   ssh -N -L 8765:127.0.0.1:8765 david@100.93.33.0     (Tunnel, offen lassen)
  2. SSH-Session da-hub:    ~/stacks/google-ads/venv/bin/python ~/stacks/google-ads/ads_auth.py
  3. Browser (Laptop):      die ausgegebene Adresse oeffnen, mit kramergastronomie@gmail.com
                            anmelden und zustimmen; die Weiterleitung auf http://127.0.0.1:8765/
                            laeuft durch den Tunnel zu diesem Skript.

Modus --iphone (Anmeldung mit Passkey direkt in Safari):
  1. SSH-Session da-hub:    ~/stacks/google-ads/venv/bin/python ~/stacks/google-ads/ads_auth.py --iphone
  2. iPhone: ntfy-Meldung «Google Ads: Anmeldung» -> Taste «1 Google» -> in Safari anmelden, zustimmen.
     Safari landet auf http://127.0.0.1:8765/?state=…&code=… («Verbindung nicht moeglich» ist richtig).
     Adresse aus der Adresszeile kopieren.
  3. iPhone: in derselben Meldung Taste «2 Rueckweg» -> ntfy-Web-App auf dem Einmal-Topic (nur Tailnet)
     -> Adresse einfuegen und senden. Das Skript fragt das Topic lokal ab (127.0.0.1:9092).
  Gleicher Client, gleiche redirect_uri, PKCE (S256) und state wie im Tunnel-Modus; der Flow bleibt in
  diesem Prozess, bis der Code eingeloest ist. Zeitlimit 10 Minuten. Code und Adresse werden nie
  ausgegeben oder protokolliert (deshalb nicht notify.sh, das jeden Text ins Log schreibt).

In beiden Modi: access_type=offline und prompt=consent sorgen dafuer, dass Google ein Refresh-Token
liefert. Das Token wird direkt in .env (600) geschrieben und nie ausgegeben – angezeigt wird nur die Laenge.
"""
import argparse
import hmac
import json
import secrets
import sys
import time
import urllib.parse
import urllib.request

import ads_common as ac

PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{PORT}/"          # run_local_server verwendet genau diese Form
NTFY_LOKAL = "http://127.0.0.1:9092"
NTFY_EXTERN = "https://da-hub.taile9dad7.ts.net:10000"   # tailnet only (tailscale serve)
NTFY_MELDETOPIC = "dahub-alerts"
ZEITLIMIT = 600
ABFRAGE_ALLE = 3


class RueckwegFehler(Exception):
    """Weiterleitungsadresse unbrauchbar (Text enthaelt nie Code, state oder Adresse)."""


class Zeitueberschreitung(Exception):
    pass


def abschluss(creds):
    """Refresh-Token in .env schreiben (nur Laenge anzeigen) und Gegenprobe (lesend)."""
    token = creds.refresh_token or ""
    if not token:
        print("FEHLER: Google hat kein Refresh-Token geliefert (Zustimmung erneut erteilen, prompt=consent)."); return 1
    ac._GEHEIM.append(token)
    ac.env_wert_schreiben("GOOGLE_ADS_REFRESH_TOKEN", token)
    print(f"Refresh-Token gespeichert in {ac.ENV_DATEI} (Laenge {len(token)}, Rechte 600)")

    # Gegenprobe, nur lesend: welche Konten darf diese Anmeldung sehen?
    try:
        client = ac.ads_client()
        kunden = client.get_service("CustomerService").list_accessible_customers().resource_names
        ids = [r.split("/")[-1] for r in kunden]
        print(f"Zugaengliche Konten: {len(ids)} – {', '.join(ids)}")
        print("Konto 5777888366 enthalten:", "ja" if ac.STANDARD_KUNDE in ids else "NEIN")
    except Exception as e:
        print("Gegenprobe fehlgeschlagen:", ac.fehler_text(e)); return 1
    return 0


def tunnel_modus():
    try:
        ac.client_json_laden()                                   # Rechte + Inhalt pruefen, bevor der Browser dran ist
    except ac.KonfigFehler as e:
        print(ac.fehler_text(e)); return 2
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(ac.CLIENT_JSON, scopes=[ac.SCOPE])
    print(f"Lokaler Empfaenger: http://127.0.0.1:{PORT}/ (nur auf 127.0.0.1, erreichbar ueber den SSH-Tunnel)")
    try:
        creds = flow.run_local_server(
            host="127.0.0.1", bind_addr="127.0.0.1", port=PORT, open_browser=False,
            access_type="offline", prompt="consent",
            authorization_prompt_message="Diese Adresse im Browser auf dem Laptop oeffnen:\n{url}\n",
            success_message="Anmeldung abgeschlossen. Dieses Fenster kann geschlossen werden.",
        )
    except Exception as e:  # Abbruch, Port belegt, Zustimmung verweigert
        print("Anmeldung fehlgeschlagen:", ac.fehler_text(e)); return 1
    return abschluss(creds)


# ---------- Modus --iphone ----------

def weiterleitung_pruefen(roh, state_erwartet):
    """Prueft die aus Safari kopierte Weiterleitungsadresse.
    -> (adresse_fuer_oauthlib, code). Entfernt Leerzeichen/Zeilenumbrueche vom Kopieren.
    oauthlib verlangt https im authorization_response (wie run_local_server: nur das Schema wird ersetzt)."""
    if not isinstance(roh, str):
        raise RueckwegFehler("keine Adresse erhalten")
    adresse = "".join(roh.split()).strip("<>\"'")
    teile = urllib.parse.urlsplit(adresse)
    if teile.scheme != "http" or teile.netloc != f"127.0.0.1:{PORT}" or teile.path not in ("", "/"):
        raise RueckwegFehler(f"keine Weiterleitung auf {REDIRECT_URI} (ganze Adresse aus der Safari-Adresszeile kopieren)")
    q = urllib.parse.parse_qs(teile.query, keep_blank_values=True)
    st = q.get("state", [])
    if len(st) != 1 or not hmac.compare_digest(st[0].encode(), state_erwartet.encode()):
        raise RueckwegFehler("state stimmt nicht ueberein (Adresse gehoert nicht zu diesem Anmeldevorgang) – abgebrochen")
    if "error" in q:
        grund = "".join(c for c in q["error"][0] if c.isalnum() or c == "_")[:40]
        raise RueckwegFehler(f"Google meldet Fehler «{grund}» (z. B. Zustimmung verweigert)")
    code = q.get("code", [""])
    if len(code) != 1 or not code[0].strip():
        raise RueckwegFehler("code fehlt in der Adresse")
    return "https" + adresse[len("http"):], code[0]


def ntfy_abrufen(topic, seit):
    """Nachrichten seit Zeitpunkt (Unix-Sekunden), lokal, ohne Streaming. -> Liste von dict."""
    url = f"{NTFY_LOKAL}/{topic}/json?poll=1&since={seit}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return [json.loads(z) for z in r.read().decode("utf-8").splitlines() if z.strip()]


def auf_rueckweg_warten(topic, frist, seit, abrufen=ntfy_abrufen, jetzt=time.monotonic, schlafen=time.sleep):
    """-> Text der ersten Nachricht auf dem Einmal-Topic; Zeitueberschreitung nach Ablauf der Frist."""
    while True:
        if jetzt() >= frist:
            raise Zeitueberschreitung()
        try:
            for m in abrufen(topic, seit):
                if m.get("event") == "message" and m.get("message"):
                    return m["message"]
        except OSError as e:             # ntfy kurz nicht erreichbar: weiter versuchen bis zur Frist
            print(f"   ntfy-Abfrage fehlgeschlagen ({type(e).__name__}), neuer Versuch")
        schlafen(ABFRAGE_ALLE)


def ntfy_senden(nachricht):
    """Direkt an ntfy (JSON-Publish), nicht ueber notify.sh – der Text wird nirgends protokolliert."""
    daten = json.dumps(nachricht).encode("utf-8")
    req = urllib.request.Request(NTFY_LOKAL + "/", data=daten, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status != 200:
            raise OSError(f"ntfy HTTP {r.status}")


def iphone_modus(abrufen=ntfy_abrufen, senden=ntfy_senden, jetzt=time.monotonic, schlafen=time.sleep):
    try:
        ac.client_json_laden()
    except ac.KonfigFehler as e:
        print(ac.fehler_text(e)); return 2
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(ac.CLIENT_JSON, scopes=[ac.SCOPE], redirect_uri=REDIRECT_URI)
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")   # PKCE S256 automatisch
    topic = "ga-rueck-" + secrets.token_urlsafe(24)       # 192 Bit Zufall, nur fuer diesen Vorgang
    rueckweg = f"{NTFY_EXTERN}/{topic}"
    ac._GEHEIM.append(state)
    seit = int(time.time()) - 5
    frist = jetzt() + ZEITLIMIT

    try:
        senden({
            "topic": NTFY_MELDETOPIC, "priority": 4, "title": "Google Ads: Anmeldung",
            "message": ("1) «1 Google» antippen, in Safari mit Passkey anmelden und zustimmen.\n"
                        "2) Safari zeigt «Verbindung nicht möglich» – ganze Adresse aus der Adresszeile kopieren.\n"
                        "3) «2 Rückweg» antippen, Adresse einfügen, senden.\nGültig 10 Minuten."),
            "click": auth_url,
            "actions": [{"action": "view", "label": "1 Google", "url": auth_url},
                        {"action": "view", "label": "2 Rückweg", "url": rueckweg}],
        })
        print("ntfy-Meldung mit Anmeldelink gesendet (Topic dahub-alerts).")
    except OSError as e:
        print(f"WARNUNG: ntfy-Versand fehlgeschlagen ({type(e).__name__}) – Links unten von Hand aufs iPhone bringen.")
    print(f"\nAnmeldeadresse (Safari auf dem iPhone):\n{auth_url}\n")
    print(f"Rueckweg (ntfy-Web-App, nur Tailnet):\n{rueckweg}\n")
    print(f"Warte auf die Weiterleitungsadresse, hoechstens {ZEITLIMIT // 60} Minuten …")

    try:
        roh = auf_rueckweg_warten(topic, frist, seit, abrufen=abrufen, jetzt=jetzt, schlafen=schlafen)
    except Zeitueberschreitung:
        print("ABBRUCH: Zeitlimit 10 Minuten ueberschritten, nichts geschrieben.")
        try:
            senden({"topic": NTFY_MELDETOPIC, "title": "Google Ads: Anmeldung abgebrochen", "message": "Zeitlimit 10 Minuten überschritten, nichts geschrieben."})
        except OSError:
            pass
        return 1
    except KeyboardInterrupt:
        print("\nABBRUCH von Hand, nichts geschrieben."); return 1
    ac._GEHEIM.append(roh)
    try:
        antwort, code = weiterleitung_pruefen(roh, state)
    except RueckwegFehler as e:
        print("ABBRUCH:", e, "– nichts geschrieben."); return 1
    ac._GEHEIM.extend([code, antwort])
    print(f"Weiterleitung empfangen, state geprueft (Code-Laenge {len(code)}). Code wird eingeloest …")
    try:
        flow.fetch_token(authorization_response=antwort)       # sendet code_verifier (PKCE) und client_secret
    except Exception as e:
        print("Einloesen fehlgeschlagen:", ac.fehler_text(e)); return 1
    rc = abschluss(flow.credentials)
    try:
        senden({"topic": NTFY_MELDETOPIC, "title": "Google Ads: Anmeldung " + ("abgeschlossen" if rc == 0 else "mit Fehler"),
                "message": "Ergebnis im Terminal (SSH-Session da-hub)."})
    except OSError:
        pass
    return rc


def main(argv=None):
    p = argparse.ArgumentParser(description="Einmalige OAuth-Anmeldung fuer Google Ads")
    p.add_argument("--iphone", action="store_true", help="Anmeldung in Safari auf dem iPhone, Rueckweg ueber ntfy-Einmal-Topic")
    a = p.parse_args(argv)
    return iphone_modus() if a.iphone else tunnel_modus()


if __name__ == "__main__":
    sys.exit(main())
