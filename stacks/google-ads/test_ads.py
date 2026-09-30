#!/usr/bin/env python3
"""Mocktests Google Ads Etappe 1a (ohne Netz, ohne echte Secrets)."""
import io
import json
import os
import stat
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

import ads_common as ac

GEHEIM_TOKEN = "1//0gGEHEIMES-refresh-token-abcdefghijklmnop"
GEHEIM_SECRET = "GOCSPX-geheimes-client-secret-xyz"


class Basis(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.chmod(self.dir, 0o700)
        ac._GEHEIM.clear()

    def datei(self, name, inhalt, modus=0o600):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(inhalt)
        os.chmod(p, modus)
        return p

    def client_json(self, **installed):
        d = {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": GEHEIM_SECRET,
             "redirect_uris": ["http://localhost"], "token_uri": "https://oauth2.googleapis.com/token"}
        d.update(installed)
        return self.datei("oauth-client.json", json.dumps({"installed": d}))


class Konfiguration(Basis):
    def test_client_json_ok(self):
        self.assertEqual(ac.client_json_laden(self.client_json()), ("123-abc.apps.googleusercontent.com", GEHEIM_SECRET))

    def test_fehlende_datei(self):
        with self.assertRaisesRegex(ac.KonfigFehler, "fehlt"):
            ac.client_json_laden(os.path.join(self.dir, "gibtsnicht.json"))
        with self.assertRaisesRegex(ac.KonfigFehler, "fehlt"):
            ac.env_laden(os.path.join(self.dir, "keine-env"))

    def test_falsche_rechte(self):
        p = self.client_json(); os.chmod(p, 0o644)
        with self.assertRaisesRegex(ac.KonfigFehler, r"zu offene Rechte \(644\), erwartet 600"):
            ac.client_json_laden(p)
        e = self.datei("env", f"GOOGLE_ADS_REFRESH_TOKEN={GEHEIM_TOKEN}\n", 0o640)
        with self.assertRaisesRegex(ac.KonfigFehler, r"zu offene Rechte \(640\)"):
            ac.env_laden(e)

    def test_client_json_unvollstaendig(self):
        with self.assertRaisesRegex(ac.KonfigFehler, "client_id oder client_secret leer"):
            ac.client_json_laden(self.client_json(client_secret=""))
        p = self.datei("web.json", json.dumps({"web": {"client_id": "x", "client_secret": "y"}}))
        with self.assertRaisesRegex(ac.KonfigFehler, "'installed' fehlt"):
            ac.client_json_laden(p)
        p = self.datei("kaputt.json", "{kein json")
        with self.assertRaisesRegex(ac.KonfigFehler, "kein gueltiges JSON"):
            ac.client_json_laden(p)

    def test_leeres_oder_fehlendes_token(self):
        for inhalt in ("GOOGLE_ADS_REFRESH_TOKEN=\n", "GOOGLE_ADS_REFRESH_TOKEN=''\n", "# nur Kommentar\n", "ANDERES=1\n"):
            e = self.datei("env", inhalt)
            with self.assertRaisesRegex(ac.KonfigFehler, "fehlt oder ist leer"):
                ac.env_laden(e)

    def test_env_ok_und_kunden_id(self):
        e = self.datei("env", f'export GOOGLE_ADS_REFRESH_TOKEN="{GEHEIM_TOKEN}"\nGOOGLE_ADS_CUSTOMER_ID=577-788-8366\n')
        self.assertEqual(ac.env_laden(e), {"GOOGLE_ADS_REFRESH_TOKEN": GEHEIM_TOKEN, "GOOGLE_ADS_CUSTOMER_ID": "5777888366"})
        e = self.datei("env", f"GOOGLE_ADS_REFRESH_TOKEN={GEHEIM_TOKEN}\n")
        self.assertEqual(ac.env_laden(e)["GOOGLE_ADS_CUSTOMER_ID"], ac.STANDARD_KUNDE)
        e = self.datei("env", f"GOOGLE_ADS_REFRESH_TOKEN={GEHEIM_TOKEN}\nGOOGLE_ADS_CUSTOMER_ID=12345\n")
        with self.assertRaisesRegex(ac.KonfigFehler, "10 Ziffern"):
            ac.env_laden(e)

    def test_env_wert_schreiben(self):
        p = os.path.join(self.dir, "env")
        puffer = io.StringIO()
        with redirect_stdout(puffer):
            ac.env_wert_schreiben("GOOGLE_ADS_REFRESH_TOKEN", "alt", p)
            with open(p, "a") as f:
                f.write("GOOGLE_ADS_CUSTOMER_ID=5777888366\n")
            ac.env_wert_schreiben("GOOGLE_ADS_REFRESH_TOKEN", GEHEIM_TOKEN, p)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        inhalt = open(p).read()
        self.assertEqual(inhalt.count("GOOGLE_ADS_REFRESH_TOKEN="), 1)          # ersetzt, nicht angehaengt
        self.assertIn(f"GOOGLE_ADS_REFRESH_TOKEN={GEHEIM_TOKEN}", inhalt)
        self.assertIn("GOOGLE_ADS_CUSTOMER_ID=5777888366", inhalt)              # andere Zeilen bleiben
        self.assertNotIn(GEHEIM_TOKEN, puffer.getvalue())                        # nichts ausgegeben
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith(".env.")], [])   # keine Temp-Reste


class Fehlerausgabe(Basis):
    def ads_fehler(self, feld, wert, meldung):
        code = types.SimpleNamespace(**{feld: types.SimpleNamespace(name=wert)})
        err = types.SimpleNamespace(error_code=code, message=meldung)
        klasse = type("GoogleAdsException", (Exception,), {})
        exc = klasse("x"); exc.failure = types.SimpleNamespace(errors=[err]); exc.request_id = "ABC123"
        return exc

    def test_quota(self):
        t = ac.fehler_text(self.ads_fehler("quota_error", "RESOURCE_EXHAUSTED", "Too many requests"))
        self.assertIn("quota_error=RESOURCE_EXHAUSTED", t)
        self.assertIn("2'880 Operationen/Tag", t)
        self.assertIn("Request-ID ABC123", t)

    def test_autorisierung_ohne_token(self):
        ac._GEHEIM.append(GEHEIM_TOKEN)
        t = ac.fehler_text(self.ads_fehler("authorization_error", "USER_PERMISSION_DENIED",
                                           f"User doesn't have permission, token {GEHEIM_TOKEN}"))
        self.assertIn("authorization_error=USER_PERMISSION_DENIED", t)
        self.assertIn("Zugriff:", t)
        self.assertNotIn(GEHEIM_TOKEN, t)

    def test_refresh_error(self):
        klasse = type("RefreshError", (Exception,), {})
        ac._GEHEIM.append(GEHEIM_SECRET)
        t = ac.fehler_text(klasse(f"invalid_grant: client {GEHEIM_SECRET}"))
        self.assertIn("ads_auth.py erneut ausfuehren", t)
        self.assertNotIn(GEHEIM_SECRET, t)

    def test_allgemein_und_konfig(self):
        ac._GEHEIM.append(GEHEIM_TOKEN)
        self.assertNotIn(GEHEIM_TOKEN, ac.fehler_text(ValueError(f"kaputt {GEHEIM_TOKEN}")))
        self.assertEqual(ac.fehler_text(ac.KonfigFehler("x fehlt")), "Konfiguration: x fehlt")


class Client(Basis):
    def test_ohne_developer_token_und_login_customer_id(self):
        k = {"client_id": "cid", "client_secret": GEHEIM_SECRET, "refresh_token": GEHEIM_TOKEN, "customer_id": "5777888366"}
        with mock.patch("google.ads.googleads.client.GoogleAdsClient.load_from_dict") as lfd:
            ac.ads_client(k)
        cfg, kw = lfd.call_args.args[0], lfd.call_args.kwargs
        self.assertNotIn("developer_token", cfg)
        self.assertNotIn("login_customer_id", cfg)
        self.assertIs(cfg["use_proto_plus"], True)
        self.assertEqual(kw["version"], "v25")

    def test_ads_check_ausgabe_und_fehler(self):
        import ads_check
        def zeile(i, name, status, kanal, micros):
            return types.SimpleNamespace(
                campaign=types.SimpleNamespace(id=i, name=name, status=types.SimpleNamespace(name=status),
                                               advertising_channel_type=types.SimpleNamespace(name=kanal)),
                campaign_budget=types.SimpleNamespace(amount_micros=micros))
        konto = [types.SimpleNamespace(customer=types.SimpleNamespace(descriptive_name="Test AG", currency_code="CHF", time_zone="Europe/Zurich"))]
        kamp = [zeile(1, "A", "PAUSED", "SEARCH", 25_000_000), zeile(2, "B", "ENABLED", "SEARCH", 10_500_000), zeile(3, "C", "PAUSED", "DISPLAY", 0)]
        svc = mock.Mock()
        svc.search_stream.side_effect = [[types.SimpleNamespace(results=konto)], [types.SimpleNamespace(results=kamp)]]
        client = mock.Mock(); client.get_service.return_value = svc
        with mock.patch.object(ac, "konfig", return_value={"customer_id": "5777888366"}), \
             mock.patch.object(ac, "ads_client", return_value=client):
            puffer = io.StringIO()
            with redirect_stdout(puffer):
                rc = ads_check.main()
        aus = puffer.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("«Test AG», Waehrung CHF, Zeitzone Europe/Zurich", aus)
        self.assertIn("Kampagnen: 3 – ENABLED 1, PAUSED 2", aus)
        self.assertIn("25.00 CHF/Tag", aus)
        # nur Leseabfragen
        self.assertEqual([c.args[0] for c in client.get_service.call_args_list], ["GoogleAdsService"])
        self.assertTrue(all("SELECT" in c.kwargs["query"] for c in svc.search_stream.call_args_list))
        # Fehlerfall: Konfiguration fehlt
        with mock.patch.object(ac, "konfig", side_effect=ac.KonfigFehler(".env fehlt")):
            puffer = io.StringIO()
            with redirect_stdout(puffer):
                rc = ads_check.main()
        self.assertEqual(rc, 1)
        self.assertIn("FEHLER: Konfiguration: .env fehlt", puffer.getvalue())


class IphoneModus(Basis):
    STATE = "StAtE-0123456789abcdef"
    CODE = "4/0AVGgeheimer-einmal-code-XYZ"

    def adresse(self, **q):
        werte = {"state": self.STATE, "code": self.CODE, "scope": ac.SCOPE}
        werte.update(q)
        werte = {k: v for k, v in werte.items() if v is not None}
        return "http://127.0.0.1:8765/?" + "&".join(f"{k}={v}" for k, v in werte.items())

    def test_gueltige_adresse(self):
        import ads_auth
        antwort, code = ads_auth.weiterleitung_pruefen(self.adresse(), self.STATE)
        self.assertEqual(code, self.CODE)
        self.assertTrue(antwort.startswith("https://127.0.0.1:8765/?state="))

    def test_leerzeichen_und_zeilenumbruch(self):
        import ads_auth
        roh = "  " + self.adresse()[:30] + "\n" + self.adresse()[30:60] + " \r\n" + self.adresse()[60:] + "\n"
        antwort, code = ads_auth.weiterleitung_pruefen(roh, self.STATE)
        self.assertEqual(code, self.CODE)
        self.assertEqual(antwort, "https" + self.adresse()[4:])

    def test_falscher_state(self):
        import ads_auth
        for adr in (self.adresse(state="fremd"), self.adresse(state=None), self.adresse() + "&state=zweiter"):
            with self.assertRaisesRegex(ads_auth.RueckwegFehler, "state stimmt nicht") as cm:
                ads_auth.weiterleitung_pruefen(adr, self.STATE)
            self.assertNotIn(self.CODE, str(cm.exception)); self.assertNotIn(self.STATE, str(cm.exception))

    def test_fehlender_code_und_google_fehler(self):
        import ads_auth
        for adr in (self.adresse(code=None), self.adresse(code="")):
            with self.assertRaisesRegex(ads_auth.RueckwegFehler, "code fehlt"):
                ads_auth.weiterleitung_pruefen(adr, self.STATE)
        with self.assertRaisesRegex(ads_auth.RueckwegFehler, "access_denied"):
            ads_auth.weiterleitung_pruefen(self.adresse(code=None, error="access_denied"), self.STATE)

    def test_fremde_adresse(self):
        import ads_auth
        for adr in ("http://localhost:8765/?state=x&code=y", "http://127.0.0.1:9999/?state=x&code=y",
                    "https://evil.example/?state=x&code=y", "http://127.0.0.1:8765/anders?state=x&code=y", "hallo"):
            with self.assertRaisesRegex(ads_auth.RueckwegFehler, "keine Weiterleitung"):
                ads_auth.weiterleitung_pruefen(adr, self.STATE)

    def test_zeitueberschreitung_beim_warten(self):
        import ads_auth
        uhr = iter(range(0, 10_000, 3))
        schlaf = mock.Mock()
        with self.assertRaises(ads_auth.Zeitueberschreitung):
            ads_auth.auf_rueckweg_warten("t", 600, 0, abrufen=lambda t, s: [{"event": "open"}],
                                         jetzt=lambda: next(uhr), schlafen=schlaf)
        self.assertEqual(schlaf.call_count, 200)                 # 600 s / 3 s, dann Schluss

    def test_warten_erste_nachricht_und_ntfy_ausfall(self):
        import ads_auth
        antworten = [OSError("weg"), [{"event": "keepalive"}], [{"event": "open"}, {"event": "message", "message": "adr"}]]
        def abrufen(t, s):
            a = antworten.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ads_auth.auf_rueckweg_warten("t", 600, 0, abrufen=abrufen, jetzt=lambda: 0,
                                                          schlafen=lambda s: None), "adr")

    def iphone_lauf(self, rueckgabe_nachricht, abrufen=None, jetzt=None):
        """iphone_modus mit gemocktem Flow, ntfy und .env im Testverzeichnis. -> (rc, ausgabe, flow, gesendet)"""
        import ads_auth
        flow = mock.Mock()
        flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", self.STATE)
        flow.credentials = types.SimpleNamespace(refresh_token=GEHEIM_TOKEN)
        gesendet = []
        client = mock.Mock()
        client.get_service.return_value.list_accessible_customers.return_value.resource_names = ["customers/5777888366"]
        env = os.path.join(self.dir, "env")
        with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file", return_value=flow) as fcs, \
             mock.patch.object(ac, "client_json_laden", return_value=("cid", GEHEIM_SECRET)), \
             mock.patch.object(ac, "ENV_DATEI", env), \
             mock.patch.object(ac, "ads_client", return_value=client):
            puffer = io.StringIO()
            with redirect_stdout(puffer):
                rc = ads_auth.iphone_modus(
                    abrufen=abrufen or (lambda t, s: [{"event": "message", "message": rueckgabe_nachricht}]),
                    senden=gesendet.append, jetzt=jetzt or (lambda: 0), schlafen=lambda s: None)
        self.assertEqual(fcs.call_args.kwargs["redirect_uri"], "http://127.0.0.1:8765/")
        return rc, puffer.getvalue(), flow, gesendet, env

    def test_iphone_ende_zu_ende(self):
        rc, aus, flow, gesendet, env = self.iphone_lauf(" " + self.adresse() + "\n")
        self.assertEqual(rc, 0)
        flow.authorization_url.assert_called_once_with(access_type="offline", prompt="consent")
        self.assertEqual(flow.fetch_token.call_args.kwargs["authorization_response"], "https" + self.adresse()[4:])
        self.assertIn(f"GOOGLE_ADS_REFRESH_TOKEN={GEHEIM_TOKEN}", open(env).read())
        self.assertEqual(stat.S_IMODE(os.stat(env).st_mode), 0o600)
        self.assertEqual(gesendet[0]["click"], "https://accounts.google.com/o/oauth2/auth?x=1")
        self.assertRegex(gesendet[0]["actions"][1]["url"], r"^https://da-hub\.taile9dad7\.ts\.net:10000/ga-rueck-[A-Za-z0-9_-]{32}$")
        for geheim in (GEHEIM_TOKEN, self.CODE, self.adresse(), self.STATE):
            self.assertNotIn(geheim, aus)
            self.assertNotIn(geheim, json.dumps(gesendet[1:]))
        self.assertIn(f"Laenge {len(GEHEIM_TOKEN)}", aus)

    def test_iphone_falscher_state_schreibt_nichts(self):
        rc, aus, flow, gesendet, env = self.iphone_lauf(self.adresse(state="fremd"))
        self.assertEqual(rc, 1)
        self.assertIn("state stimmt nicht", aus)
        flow.fetch_token.assert_not_called()
        self.assertFalse(os.path.exists(env))
        self.assertNotIn(self.CODE, aus)

    def test_iphone_zeitueberschreitung(self):
        uhr = iter(range(0, 10_000, 30))
        rc, aus, flow, gesendet, env = self.iphone_lauf(None, abrufen=lambda t, s: [], jetzt=lambda: next(uhr))
        self.assertEqual(rc, 1)
        self.assertIn("Zeitlimit 10 Minuten", aus)
        flow.fetch_token.assert_not_called()
        self.assertFalse(os.path.exists(env))
        self.assertEqual(gesendet[-1]["title"], "Google Ads: Anmeldung abgebrochen")


if __name__ == "__main__":
    unittest.main(verbosity=1)
