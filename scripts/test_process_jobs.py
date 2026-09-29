#!/usr/bin/env python3
"""Mocktests fuer process_jobs.py (ohne Datenbank, ohne Netz)."""
import sys
import threading
import types
import unittest
from unittest import mock

import requests

import process_jobs as pj


def args(**kw):
    a = types.SimpleNamespace(docling_url="http://d:5001", ollama_url="http://o:11434",
                              nextcloud_url="http://n:8080", unoserver_url="http://u:2004",
                              nextcloud_user="u", nextcloud_password="p")
    a.__dict__.update(kw)
    return a


def antwort(code=200, js=None, text=""):
    r = mock.Mock(status_code=code, text=text, content=b"x")
    r.json.return_value = js if js is not None else {}
    return r


REFUSED = requests.ConnectionError("HTTPConnectionPool(host='d', port=5001): Max retries exceeded "
                                   "(Caused by NewConnectionError(': Failed to establish a new connection: "
                                   "[Errno 111] Connection refused'))")
ABGEBROCHEN = requests.ConnectionError("('Connection aborted.', RemoteDisconnected('Remote end closed "
                                       "connection without response'))")


class Stufe1Gesundheit(unittest.TestCase):
    def test_abgewiesen_erkannt(self):
        self.assertTrue(pj.ist_verbindung_abgewiesen(REFUSED))
        self.assertTrue(pj.ist_verbindung_abgewiesen(requests.ConnectTimeout("x")))
        self.assertFalse(pj.ist_verbindung_abgewiesen(ABGEBROCHEN))
        self.assertFalse(pj.ist_verbindung_abgewiesen(requests.ReadTimeout("x")))
        self.assertFalse(pj.ist_verbindung_abgewiesen(ValueError("x")))

    def test_dienste_gesund(self):
        def get(url, timeout):
            return antwort(js={"installed": True, "maintenance": False}) if "status.php" in url else antwort()
        with mock.patch.object(pj.requests, "get", side_effect=get):
            self.assertEqual(pj.dienste_pruefen(args()), [])

    def test_docling_weg(self):
        def get(url, timeout):
            if ":5001" in url:
                raise REFUSED
            return antwort(js={"installed": True, "maintenance": False}) if "status.php" in url else antwort()
        with mock.patch.object(pj.requests, "get", side_effect=get):
            p = pj.dienste_pruefen(args())
        self.assertEqual(len(p), 1)
        self.assertIn("docling", p[0])

    def test_nextcloud_wartung(self):
        def get(url, timeout):
            return antwort(js={"installed": True, "maintenance": True}) if "status.php" in url else antwort()
        with mock.patch.object(pj.requests, "get", side_effect=get):
            self.assertEqual(pj.dienste_pruefen(args()), ["nextcloud im Wartungsmodus"])

    def test_probe_erkennt_404(self):
        with mock.patch.object(pj.requests, "post", return_value=antwort(404, text='{"detail":"Task result not found"}')):
            self.assertIn("HTTP 404", pj.docling_probe(args()))
        ok = antwort(js={"status": "success", "document": {"md_content": f"# Probe\n{pj.PROBE_MERKWORT}"}})
        with mock.patch.object(pj.requests, "post", return_value=ok) as post:
            self.assertIsNone(pj.docling_probe(args()))
            self.assertEqual(post.call_args.kwargs["data"], pj.DOCLING_FELDER)

    def test_extract_text_abgewiesen_vs_abgebrochen(self):
        with mock.patch.object(pj.requests, "request", side_effect=REFUSED):
            with self.assertRaises(pj.DienstNichtErreichbar):
                pj.extract_text("http://d:5001", "http://u", "a.pdf", b"x")
        with mock.patch.object(pj.requests, "request", side_effect=ABGEBROCHEN):
            with self.assertRaises(requests.ConnectionError):  # zaehlt als Versuch
                pj.extract_text("http://d:5001", "http://u", "a.pdf", b"x")

    def test_download_503_und_abgewiesen(self):
        s = mock.Mock()
        s.get.return_value = antwort(503)
        with self.assertRaises(pj.DienstNichtErreichbar):
            pj.download_file(s, "http://n", "/x/a.pdf")
        s.get.side_effect = REFUSED
        with self.assertRaises(pj.DienstNichtErreichbar):
            pj.download_file(s, "http://n", "/x/a.pdf")

    def test_libreoffice_abgewiesen(self):
        with mock.patch.object(pj.requests, "request", side_effect=REFUSED):
            with self.assertRaises(pj.DienstNichtErreichbar):
                pj.convert_legacy("http://u", "a.xls", b"x")

    def test_thread_gibt_job_zurueck_und_stoppt(self):
        stopp, lock, z = threading.Event(), threading.Lock(), {"ok": 0, "fail": 0, "cancelled": 0, "zurueck": 0}
        conn = mock.MagicMock()
        job = {"id": 7, "origin_path": "/a/b.pdf", "action": "created", "old_path": None}
        with mock.patch.object(pj.psycopg2, "connect", return_value=conn), \
             mock.patch.object(pj, "process_one", side_effect=pj.DienstNichtErreichbar("docling nicht erreichbar")), \
             mock.patch.object(pj, "job_zurueckgeben") as zurueck, mock.patch.object(pj, "finish_job") as fertig:
            pj.verarbeite_job_isoliert(job, args(), {}, z, lock, stopp)
        self.assertTrue(stopp.is_set())
        zurueck.assert_called_once()
        fertig.assert_not_called()
        self.assertEqual(z["zurueck"], 1)
        self.assertEqual(z["fail"], 0)

    def test_job_zurueckgeben_sql(self):
        conn = mock.MagicMock()
        pj.job_zurueckgeben(conn, 7, "grund")
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        self.assertIn("attempts = GREATEST(attempts - 1, 0)", sql)
        self.assertIn("status = 'pending'", sql)
        self.assertIn("status = 'processing'", sql)

    def _main(self, gesund_folge, probe=None):
        argv = ["x", "--nextcloud-url", "http://n", "--nextcloud-user", "u", "--nextcloud-password", "p",
                "--docling-url", "http://d", "--ollama-url", "http://o", "--pg-host", "h", "--pg-db", "d",
                "--pg-user", "u", "--pg-password", "p", "--limit", "10", "--parallel", "2"]
        claims = []
        def claim(conn, n):
            claims.append(n)
            return [{"id": len(claims), "origin_path": "/a.pdf", "action": "created", "old_path": None}]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(pj, "dienste_pruefen", side_effect=gesund_folge), \
             mock.patch.object(pj, "docling_probe", return_value=probe), \
             mock.patch.object(pj.psycopg2, "connect", return_value=mock.MagicMock()), \
             mock.patch.object(pj, "recover_stale_jobs", return_value=(0, 0, 0)), \
             mock.patch.object(pj, "claim_jobs", side_effect=claim), \
             mock.patch.object(pj, "verarbeite_job_isoliert"):
            rc = pj.main()
        return rc, claims

    def test_main_ohne_claim_wenn_docling_weg(self):
        rc, claims = self._main([["docling nicht erreichbar"]])
        self.assertEqual((rc, claims), (3, []))

    def test_main_ohne_claim_wenn_probe_rot(self):
        rc, claims = self._main([[]], probe="docling-Probe: HTTP 404")
        self.assertEqual((rc, claims), (3, []))

    def test_main_stoppt_mitten_im_lauf(self):
        # Start gesund, Runde 1 gesund, vor Runde 2 docling weg
        rc, claims = self._main([[], [], ["docling nicht erreichbar"]])
        self.assertEqual(rc, 3)
        self.assertEqual(len(claims), 1)

    def test_simulation_schreibt_nichts(self):
        job = {"id": 5, "origin_path": "/W/a.pdf", "action": "created", "old_path": None}
        sess = mock.Mock(); sess.get.return_value = antwort(200)
        with mock.patch.object(pj, "extract_text", return_value="Text " * 50), \
             mock.patch.object(pj, "embed_batch", side_effect=lambda u, t: [[0.0] * 1024] * len(t)), \
             mock.patch.object(pj, "store_document") as store:
            info = pj.process_one(job, sess, args(), None, simulieren=True)
        store.assert_not_called()
        self.assertIn("Chunks", info)

    def test_ohne_namen(self):
        t = pj.ohne_namen("Download fehlgeschlagen (404) für /W/Ordner/Rechnung Müller.pdf", "/W/Ordner/Rechnung Müller.pdf")
        self.assertNotIn("Müller", t)


def jpeg(x, y, exif_zuerst=False):
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x01" + x.to_bytes(2, "big") + y.to_bytes(2, "big") + b"\x00\x00"
    app14 = b"\xff\xee\x00\x0eAdobe\x00d\x00\x00\x00\x00\x01"
    exif = b"\xff\xe1\x00\x08Exif\x00\x00"
    rest = b"\xff\xdb\x00\x04\x00\x00\xff\xda\x00\x02" + b"\x12\x34" * 50 + b"\xff\xd9"
    return b"\xff\xd8" + ((exif + app0) if exif_zuerst else app0) + app14 + rest


class Stufe2Jpeg(unittest.TestCase):
    def test_dichte_null_korrigiert(self):
        alt = jpeg(0, 0)
        neu, k = pj.jfif_dichte_korrigieren(alt)
        self.assertTrue(k)
        self.assertEqual(len(neu), len(alt))
        self.assertEqual(neu[14:18], (96).to_bytes(2, "big") * 2)
        diff = [i for i in range(len(alt)) if alt[i] != neu[i]]
        self.assertTrue(all(14 <= i < 18 for i in diff))  # nur die 4 Dichte-Bytes

    def test_eine_dichte_null(self):
        neu, k = pj.jfif_dichte_korrigieren(jpeg(72, 0))
        self.assertTrue(k)
        self.assertEqual(neu[14:18], (72).to_bytes(2, "big") * 2)

    def test_dichte_gesetzt_unveraendert(self):
        alt = jpeg(72, 72)
        self.assertEqual(pj.jfif_dichte_korrigieren(alt), (alt, False))

    def test_jfif_nach_exif(self):
        neu, k = pj.jfif_dichte_korrigieren(jpeg(0, 0, exif_zuerst=True))
        self.assertTrue(k)

    def test_kein_jpeg_unveraendert(self):
        for b in (b"%PDF-1.4 ...", b"\x89PNG\r\n\x1a\n....", b"", b"\xff\xd8"):
            self.assertEqual(pj.jfif_dichte_korrigieren(b), (b, False))

    def test_process_one_hash_vom_original(self):
        alt = jpeg(0, 0)
        sess = mock.Mock(); sess.get.return_value = mock.Mock(status_code=200, content=alt)
        gesendet = {}
        def extract(d, u, name, inhalt):
            gesendet["inhalt"] = inhalt
            return "Text " * 20
        with mock.patch.object(pj, "extract_text", side_effect=extract), \
             mock.patch.object(pj, "embed_batch", side_effect=lambda u, t: [[0.0] * 1024] * len(t)), \
             mock.patch.object(pj, "store_document") as store:
            info = pj.process_one({"id": 1, "origin_path": "/a.jpg", "action": "created", "old_path": None},
                                  sess, args(), mock.MagicMock())
        self.assertIn("JFIF-Dichte korrigiert", info)
        self.assertNotEqual(gesendet["inhalt"], alt)
        self.assertEqual(store.call_args.args[4], pj.hashlib.sha256(alt).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=1)
