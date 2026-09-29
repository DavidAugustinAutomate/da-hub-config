#!/usr/bin/env python3
"""Mocktests fuer process_jobs.py (ohne Datenbank, ohne Netz)."""
import io
import sys
import threading
import types
import unittest
import zipfile
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

    def test_simulation_ohne_embedding(self):
        job = {"id": 5, "origin_path": "/W/a.pdf", "action": "created", "old_path": None}
        sess = mock.Mock(); sess.get.return_value = antwort(200)
        with mock.patch.object(pj, "extract_text", return_value="Text " * 900), \
             mock.patch.object(pj, "embed_batch") as emb, mock.patch.object(pj, "store_document") as store:
            info = pj.process_one(job, sess, args(ohne_embedding=True), None, simulieren=True)
        emb.assert_not_called(); store.assert_not_called()
        self.assertIn("4500 Zeichen", info)

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


class Stufe3NameErrorNul(unittest.TestCase):
    def test_libreoffice_fehler_ohne_nameerror(self):
        r = mock.Mock(status_code=500, text="kaputt", content=b"")
        with mock.patch.object(pj.requests, "request", return_value=r):
            with self.assertRaises(RuntimeError) as cm:
                pj.convert_legacy("http://u", "Tabelle.xls", b"x")
        self.assertIn("LibreOffice-Fehler (500) bei .xls", str(cm.exception))

    def test_nul_entfernt(self):
        sess = mock.Mock(); sess.get.return_value = mock.Mock(status_code=200, content=b"%PDF")
        with mock.patch.object(pj, "extract_text", return_value="Anfang\x00Mitte\x00 Ende " * 10), \
             mock.patch.object(pj, "embed_batch", side_effect=lambda u, t: [[0.0] * 1024] * len(t)), \
             mock.patch.object(pj, "store_document") as store:
            info = pj.process_one({"id": 1, "origin_path": "/a.pdf", "action": "created", "old_path": None},
                                  sess, args(), mock.MagicMock())
        chunks = store.call_args.args[5]
        self.assertTrue(chunks and all("\x00" not in c for c in chunks))
        self.assertIn("NUL-Zeichen entfernt", info)


def xlsx(shared=True):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   '<sheet name="Umsatz" sheetId="1" r:id="rId1"/><sheet name="Leer" sheetId="2" r:id="rId2"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
        if shared:
            z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       '<si><t>Standort</t></si><si><r><t>Zü</t></r><r><t>rich</t></r></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                   '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Betrag</t></is></c></row>'
                   '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>1234.5</v></c><c r="C2"/></row>'
                   '<row r="3"></row></sheetData></worksheet>')
        z.writestr("xl/worksheets/sheet2.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')
    return b.getvalue()


class Stufe4CsvExcel(unittest.TestCase):
    def test_csv_semikolon_cp1252(self):
        t = pj.csv_text("Name;Ort;Betrag\nMüller;Zürich;12,50\n;;\n".encode("cp1252"))
        self.assertEqual(t.splitlines(), ["Name | Ort | Betrag", "Müller | Zürich | 12,50"])

    def test_csv_komma_utf8_bom_quotes(self):
        t = pj.csv_text('﻿a,b\n"x, y",z\n'.encode("utf-8"))
        self.assertEqual(t.splitlines(), ["a | b", "x, y | z"])

    def test_csv_nul_und_unbekannt(self):
        t = pj.csv_text(b"eins\x00zwei\n\xff\xfe drei\n")
        self.assertNotIn("\x00", t)
        self.assertTrue(t)

    def test_csv_geht_nicht_an_docling(self):
        with mock.patch.object(pj.requests, "request") as r:
            self.assertIn("a | b", pj.extract_text("http://d", "http://u", "x.CSV", b"a;b\n1;2\n"))
        r.assert_not_called()

    def test_xlsx_text(self):
        t = pj.xlsx_text(xlsx())
        self.assertEqual(t.splitlines(), ["## Blatt: Umsatz", "Standort | Betrag", "Zürich | 1234.5", "## Blatt: Leer"])

    def test_xlsx_ohne_shared_strings(self):
        self.assertIn("Betrag", pj.xlsx_text(xlsx(shared=False)))

    def test_xlsx_geht_nicht_an_docling(self):
        with mock.patch.object(pj.requests, "request") as r:
            self.assertIn("Zürich", pj.extract_text("http://d", "http://u", "a.xlsx", xlsx()))
        r.assert_not_called()

    def test_xls_ueber_libreoffice_dann_eigener_leser(self):
        lo = mock.Mock(status_code=200, content=xlsx(), text="")
        with mock.patch.object(pj.requests, "request", return_value=lo) as r:
            t = pj.extract_text("http://d", "http://u", "alt.xls", b"\xd0\xcf\x11\xe0")
        self.assertIn("Zürich", t)
        self.assertEqual(r.call_count, 1)  # nur LibreOffice, kein docling

    def test_kaputtes_xlsx_faellt_auf_docling_zurueck(self):
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"status": "success", "document": {"md_content": "aus docling"}}
        with mock.patch.object(pj.requests, "request", return_value=ok) as r:
            self.assertEqual(pj.extract_text("http://d", "http://u", "kaputt.xlsx", b"kein zip"), "aus docling")
        self.assertIn("/v1/convert/file", r.call_args.args[1])

    def test_grenze(self):
        with mock.patch.object(pj, "TABELLE_MAX_ZEICHEN", 30):
            t = pj.csv_text(("abc;def\n" * 20).encode())
        self.assertTrue(t.endswith("(gekuerzt)"))


class Stufe5FristGrenze(unittest.TestCase):
    job = {"id": 1, "origin_path": "/a.xlsx", "action": "created", "old_path": None}

    def _lauf(self, text, zeiten=None):
        sess = mock.Mock(); sess.get.return_value = mock.Mock(status_code=200, content=b"x")
        patches = [mock.patch.object(pj, "extract_text", return_value=text),
                   mock.patch.object(pj, "embed_batch", side_effect=lambda u, t: [[0.0] * 1024] * len(t)),
                   mock.patch.object(pj, "store_document")]
        if zeiten is not None:
            patches.append(mock.patch.object(pj.time, "time", side_effect=zeiten))
        with patches[0], patches[1], patches[2] as store, (patches[3] if zeiten is not None else mock.MagicMock()):
            info = pj.process_one(self.job, sess, args(), mock.MagicMock())
        return info, store

    def test_zeichengrenze(self):
        text = ("Wort " * 30 + "\n\n") * 5000   # 760'000 Zeichen
        with mock.patch.object(pj, "chunk_text", wraps=pj.chunk_text) as ct:
            info, store = self._lauf(text)
        a = store.call_args.args
        gekuerzt, gesamt = a[7], a[8]
        self.assertTrue(gekuerzt)
        self.assertEqual(gesamt, len(text))
        self.assertEqual(len(ct.call_args.args[0]), pj.MAX_TEXT_ZEICHEN)   # nur der Anfang wird zerlegt
        self.assertIn(f"von {len(text)} Zeichen", info)
        self.assertRegex(info, r"~(4\d{5}|500000) von")                     # Ueberlappung herausgerechnet

    def test_unter_grenze_nicht_gekuerzt(self):
        info, store = self._lauf("Kurzer Text " * 100)
        self.assertFalse(store.call_args.args[7])
        self.assertNotIn("gekuerzt", info)

    def test_zeitwaechter(self):
        # t0=Jobstart, t1=Umwandlung Start, t2=Ende, dann je Batch eine Abfrage:
        # Batch 1 (i=0) ohne Abfrage, Batch 2 noch jung, Batch 3 zu alt
        text = ("Satz mit Inhalt. " * 110 + "\n\n") * 100   # ~100 Chunks -> 4 Batches
        zeiten = [0, 0, 60, 600, pj.JOB_EMBED_STOPP_S + 1] + [pj.JOB_EMBED_STOPP_S + 2] * 10
        info, store = self._lauf(text, zeiten)
        a = store.call_args.args
        self.assertTrue(a[7])
        self.assertEqual(len(a[5]), 64)          # 2 Batches zu 32 eingebettet
        self.assertEqual(len(a[6]), 64)          # Chunks und Embeddings passen zusammen
        self.assertIn("gekuerzt", info)

    def test_store_sql_markierung(self):
        conn = mock.MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [("processing",), (42,)]
        with mock.patch.object(pj, "execute_values"):
            pj.store_document(conn, 1, "/a", "a", "h", ["c"], [[0.0] * 1024], True, 999)
        sqls = [c.args for c in cur.execute.call_args_list]
        ins = [s for s in sqls if "INSERT INTO documents" in s[0]][0]
        self.assertIn("text_gekuerzt", ins[0]); self.assertEqual(ins[1][-2:], (True, 999))
        ft = [s for s in sqls if "UPDATE file_tracking" in s[0]][0]
        self.assertEqual(ft[1][0], "gekuerzt")

    def test_weiche_frist_keine_neuen_jobs(self):
        argv = ["x", "--nextcloud-url", "http://n", "--nextcloud-user", "u", "--nextcloud-password", "p",
                "--docling-url", "http://d", "--ollama-url", "http://o", "--pg-host", "h", "--pg-db", "d",
                "--pg-user", "u", "--pg-password", "p", "--limit", "0", "--parallel", "2", "--weiche-frist-minuten", "25"]
        claims = []
        uhr = iter([0] + [c * 600 for c in range(1, 100)])   # jede Abfrage +10 min
        def claim(conn, n):
            claims.append(n)
            return [{"id": len(claims), "origin_path": "/a.pdf", "action": "created", "old_path": None}]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(pj, "dienste_pruefen", return_value=[]), \
             mock.patch.object(pj, "docling_probe", return_value=None), \
             mock.patch.object(pj.psycopg2, "connect", return_value=mock.MagicMock()), \
             mock.patch.object(pj, "recover_stale_jobs", return_value=(0, 0, 0)), \
             mock.patch.object(pj, "claim_jobs", side_effect=claim), \
             mock.patch.object(pj, "verarbeite_job_isoliert"), \
             mock.patch.object(pj.time, "time", side_effect=lambda: next(uhr)):
            rc = pj.main()
        self.assertEqual(rc, 0)
        self.assertEqual(len(claims), 2)   # Runde bei 10 und 20 min, bei 30 min Schluss


if __name__ == "__main__":
    unittest.main(verbosity=1)
