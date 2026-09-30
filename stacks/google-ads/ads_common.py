#!/usr/bin/env python3
"""ads_common.py – gemeinsamer Weg zum Google-Ads-Client fuer alle Skripte auf da-hub.

Seit dem 09.09.2026 gibt es keine Developer Tokens mehr (google-ads >= 32.0.0);
die Zugangsstufe haengt am Google-Cloud-Projekt des OAuth-Clients. Kein
Verwaltungskonto (MCC), kein login_customer_id.

Quellen (beide im Verzeichnis ~/stacks/google-ads, Rechte 600, Verzeichnis 700):
  oauth-client.json   Desktop-App-Client (Schluessel "installed": client_id, client_secret)
  .env                GOOGLE_ADS_REFRESH_TOKEN (von ads_auth.py geschrieben),
                      optional GOOGLE_ADS_CUSTOMER_ID (Standard 5777888366)

Secrets werden nie ausgegeben; Fehlermeldungen laufen durch schwaerzen().
"""
import json
import os
import stat
import tempfile

VERZEICHNIS = os.path.expanduser(os.environ.get("DAHUB_ADS_DIR", "~/stacks/google-ads"))
CLIENT_JSON = os.path.join(VERZEICHNIS, "oauth-client.json")
ENV_DATEI = os.path.join(VERZEICHNIS, ".env")
API_VERSION = "v25"           # google-ads 33.0.0: Google Ads API v25_2
SCOPE = "https://www.googleapis.com/auth/adwords"
STANDARD_KUNDE = "5777888366"


class KonfigFehler(Exception):
    """Konfiguration fehlt oder ist unsicher (Text enthaelt nie einen Wert)."""


_GEHEIM = []   # bekannte Secrets fuer schwaerzen()


def schwaerzen(text):
    text = str(text)
    for g in _GEHEIM:
        if g and len(g) >= 8:
            text = text.replace(g, "<geschwaerzt>")
    return text


def rechte_pruefen(pfad, name):
    """Datei muss existieren, uns gehoeren und darf fuer Gruppe/Andere nicht lesbar sein (600)."""
    try:
        st = os.stat(pfad)
    except FileNotFoundError:
        raise KonfigFehler(f"{name} fehlt: {pfad}") from None
    if not stat.S_ISREG(st.st_mode):
        raise KonfigFehler(f"{name} ist keine normale Datei: {pfad}")
    if st.st_uid != os.getuid():
        raise KonfigFehler(f"{name} gehoert nicht dem aktuellen Benutzer: {pfad}")
    modus = stat.S_IMODE(st.st_mode)
    if modus & 0o077:
        raise KonfigFehler(f"{name} hat zu offene Rechte ({modus:o}), erwartet 600: {pfad}")


def client_json_laden(pfad=None):
    """-> (client_id, client_secret) aus oauth-client.json (Desktop-App)."""
    pfad = pfad or CLIENT_JSON
    rechte_pruefen(pfad, "oauth-client.json")
    try:
        d = json.load(open(pfad, encoding="utf-8"))
    except ValueError:
        raise KonfigFehler("oauth-client.json ist kein gueltiges JSON") from None
    inst = d.get("installed")
    if not isinstance(inst, dict):
        raise KonfigFehler("oauth-client.json: Schluessel 'installed' fehlt (Client-Typ Desktop-App erwartet)")
    cid, sec = inst.get("client_id") or "", inst.get("client_secret") or ""
    if not cid.strip() or not sec.strip():
        raise KonfigFehler("oauth-client.json: client_id oder client_secret leer")
    _GEHEIM.append(sec)
    return cid.strip(), sec.strip()


def env_lesen(pfad=None):
    """KEY=VALUE-Zeilen (Kommentare/Leerzeilen erlaubt, Anfuehrungszeichen werden entfernt)."""
    pfad = pfad or ENV_DATEI
    werte = {}
    with open(pfad, encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile or zeile.startswith("#") or "=" not in zeile:
                continue
            k, v = zeile.split("=", 1)
            k, v = k.strip().removeprefix("export ").strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            werte[k] = v
    return werte


def env_laden(pfad=None):
    """-> dict mit GOOGLE_ADS_REFRESH_TOKEN (nicht leer) und GOOGLE_ADS_CUSTOMER_ID."""
    pfad = pfad or ENV_DATEI
    rechte_pruefen(pfad, ".env")
    werte = env_lesen(pfad)
    token = werte.get("GOOGLE_ADS_REFRESH_TOKEN", "").strip()
    if not token:
        raise KonfigFehler(".env: GOOGLE_ADS_REFRESH_TOKEN fehlt oder ist leer – zuerst ads_auth.py ausfuehren")
    kunde = werte.get("GOOGLE_ADS_CUSTOMER_ID", STANDARD_KUNDE).replace("-", "").strip()
    if not kunde.isdigit() or len(kunde) != 10:
        raise KonfigFehler(".env: GOOGLE_ADS_CUSTOMER_ID muss 10 Ziffern haben")
    _GEHEIM.append(token)
    return {"GOOGLE_ADS_REFRESH_TOKEN": token, "GOOGLE_ADS_CUSTOMER_ID": kunde}


def env_wert_schreiben(schluessel, wert, pfad=None):
    """Setzt/ersetzt eine Zeile KEY=VALUE atomar; Datei danach 600. Der Wert wird nie ausgegeben."""
    pfad = pfad or ENV_DATEI
    zeilen = []
    if os.path.exists(pfad):
        rechte_pruefen(pfad, ".env")
        with open(pfad, encoding="utf-8") as f:
            zeilen = [z.rstrip("\n") for z in f if not z.split("=", 1)[0].strip() == schluessel]
    zeilen.append(f"{schluessel}={wert}")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(pfad), prefix=".env.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(zeilen) + "\n")
        os.replace(tmp, pfad)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    os.chmod(pfad, 0o600)


def konfig():
    """Alle Werte fuer den Client. -> dict (enthaelt Secrets, nie ausgeben)."""
    cid, sec = client_json_laden()
    env = env_laden()
    return {"client_id": cid, "client_secret": sec,
            "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"], "customer_id": env["GOOGLE_ADS_CUSTOMER_ID"]}


def ads_client(k=None):
    """GoogleAdsClient ohne Developer Token und ohne login_customer_id, use_proto_plus."""
    from google.ads.googleads.client import GoogleAdsClient
    k = k or konfig()
    return GoogleAdsClient.load_from_dict({
        "client_id": k["client_id"],
        "client_secret": k["client_secret"],
        "refresh_token": k["refresh_token"],
        "use_proto_plus": True,
    }, version=API_VERSION)


def fehler_text(exc):
    """Verstaendliche Fehlermeldung ohne Tokens. Kennt GoogleAdsException (Fehlercodes,
    Request-ID), RefreshError (Token ungueltig/widerrufen) und Konfigurationsfehler."""
    name = type(exc).__name__
    if isinstance(exc, KonfigFehler):
        return f"Konfiguration: {exc}"
    if name == "RefreshError":
        return ("Anmeldung abgelehnt (RefreshError): Refresh-Token ungueltig, widerrufen oder "
                "zum falschen OAuth-Client gehoerig – ads_auth.py erneut ausfuehren. "
                f"Details: {schwaerzen(exc)[:200]}")
    if name == "GoogleAdsException" and hasattr(exc, "failure"):
        teile = []
        for e in getattr(exc.failure, "errors", []) or []:
            code = e.error_code
            art, wert = "?", "?"
            # proto-plus: genau ein Feld des oneof ist gesetzt
            for feld in ("authorization_error", "authentication_error", "quota_error", "request_error",
                         "query_error", "field_error", "internal_error", "header_error"):
                v = getattr(code, feld, None)
                if v:
                    art, wert = feld, getattr(v, "name", str(v))
                    break
            teile.append(f"{art}={wert}: {schwaerzen(e.message)[:200]}")
        hinweis = ""
        if any(t.startswith("quota_error") for t in teile):
            hinweis = " (Quote Explorer: 2'880 Operationen/Tag)"
        if any(t.startswith(("authorization_error", "authentication_error")) for t in teile):
            hinweis = " (Zugriff: angemeldetes Google-Konto, Kunden-ID und Cloud-Projekt pruefen)"
        rid = getattr(exc, "request_id", None) or "-"
        return f"Google Ads meldet {len(teile)} Fehler{hinweis}, Request-ID {rid}: " + " | ".join(teile)
    return f"{name}: {schwaerzen(exc)[:300]}"
