#!/usr/bin/env python3
"""
process_jobs.py

Arbeitet die Job-Queue (file_jobs) ab, die der Scanner befüllt hat:

  created/modified -> Datei aus Nextcloud laden -> Docling (Text/OCR)
                      -> Chunking -> Ollama-Embedding -> pgvector
  deleted          -> documents-Zeile löschen (chunks per CASCADE)
  moved            -> nur Pfad in documents aktualisieren, kein Re-Embedding

Aufruf:
    python3 process_jobs.py \
        --nextcloud-url http://100.93.33.0:8080 \
        --nextcloud-user wissensbasis-bot \
        --nextcloud-password '<APP-PASSWORT>' \
        --docling-url http://100.93.33.0:5001 \
        --ollama-url http://100.93.33.0:11434 \
        --pg-host 100.93.33.0 --pg-port 5432 \
        --pg-db knowledge --pg-user dahub --pg-password '<PG-PASSWORT>' \
        --limit 10

--limit begrenzt die Anzahl Jobs pro Lauf (Standard 50). Ohne Limit läuft
das Skript, bis die Queue leer ist.

Gesundheitsprüfung (seit 29.09.2026): Vor jeder Runde werden docling, Ollama
und Nextcloud geprüft, zu Beginn zusätzlich eine kleine docling-Umwandlung mit
denselben Feldern wie im Betrieb. Ist ein Dienst nicht erreichbar, endet der
Lauf, ohne weitere Jobs zu übernehmen. Wird eine Verbindung mitten im Lauf
abgewiesen, geht der Job ohne Versuchszählung zurück in die Queue.

--simulieren --job-ids 1,2,3 verarbeitet die genannten Jobs vollständig
(Download, Umwandlung, Chunking, Embedding), speichert aber nichts und ändert
keinen Job-Status. Ausgabe nur mit ID und Endung, ohne Dateinamen.
"""

import argparse
import hashlib
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
except ImportError:
    print("FEHLER: psycopg2 fehlt. Installiere mit:")
    print("  pip install psycopg2-binary --break-system-packages")
    sys.exit(1)


# Chunking-Parameter. ~500 Tokens entsprechen grob 2000 Zeichen im Deutschen;
# 200 Zeichen Überlappung, damit ein Satz an der Grenze nicht verloren geht.
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200

# Muss zur Definition von chunks.embedding vector(1024) im Schema passen
EMBEDDING_DIM = 1024

# Dateien über dieser Grösse werden übersprungen -- Docling würde daran
# sehr lange rechnen und die Queue blockieren.
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

# Gesundheitsprüfung: kurze Frist, sie läuft vor jeder Runde
GESUNDHEIT_TIMEOUT = 10
# Funktionsprobe zu Beginn des Laufs: gleiche Felder wie extract_text. Ein
# reiner /health-Test hätte docling v1.34.0 (29.09.) nicht erkannt.
DOCLING_FELDER = {"to_formats": "md", "do_ocr": "true", "ocr_lang": "deu,eng"}
PROBE_MERKWORT = "Dahubprobe4711"


class DienstNichtErreichbar(Exception):
    """Ein benötigter Dienst hat die Verbindung abgewiesen oder ist im
    Wartungsmodus. Die Datei ist daran nicht schuld: Der Job geht ohne
    Versuchszählung zurück in die Queue, und der Lauf endet."""


def ist_verbindung_abgewiesen(exc):
    """True, wenn die Verbindung gar nicht zustande kam (Dienst weg).
    Bricht sie dagegen MITTEN in der Anfrage ab, kann die Datei den Dienst
    zum Absturz gebracht haben -- dann zählt der Versuch weiter, sonst liefe
    eine solche Datei endlos in Wiederholung."""
    if isinstance(exc, requests.ConnectTimeout):
        return True
    if not isinstance(exc, requests.ConnectionError):
        return False
    text = str(exc)
    return any(s in text for s in ("Connection refused", "NewConnectionError",
                                   "Failed to establish a new connection",
                                   "Name or service not known",
                                   "Temporary failure in name resolution"))


def http(dienst, methode, url, **kwargs):
    """requests-Aufruf, der eine abgewiesene Verbindung als
    DienstNichtErreichbar meldet. Alle übrigen Fehler bleiben unverändert."""
    try:
        return requests.request(methode, url, **kwargs)
    except requests.RequestException as exc:
        if ist_verbindung_abgewiesen(exc):
            raise DienstNichtErreichbar(f"{dienst} nicht erreichbar: {type(exc).__name__}") from exc
        raise


def dienste_pruefen(args):
    """Liste der Probleme; leer = alle Dienste bereit."""
    probleme = []
    for name, url in (("docling", urljoin(args.docling_url, "/health")),
                      ("ollama", urljoin(args.ollama_url, "/api/version")),
                      ("nextcloud", urljoin(args.nextcloud_url, "/status.php"))):
        try:
            r = requests.get(url, timeout=GESUNDHEIT_TIMEOUT)
        except requests.RequestException as exc:
            probleme.append(f"{name} nicht erreichbar ({type(exc).__name__})")
            continue
        if r.status_code != 200:
            probleme.append(f"{name} HTTP {r.status_code}")
            continue
        if name == "nextcloud":
            try:
                d = r.json()
            except ValueError:
                probleme.append("nextcloud: status.php ohne JSON")
                continue
            if d.get("maintenance") or not d.get("installed"):
                probleme.append("nextcloud im Wartungsmodus")
    return probleme


def docling_probe(args):
    """Kleine Umwandlung mit den Betriebsfeldern. None = in Ordnung, sonst Grund."""
    try:
        r = requests.post(urljoin(args.docling_url, "/v1/convert/file"),
                          files={"files": ("probe.md", f"# Probe\n\n{PROBE_MERKWORT}\n".encode())},
                          data=DOCLING_FELDER, timeout=120)
    except requests.RequestException as exc:
        return f"docling-Probe: {type(exc).__name__}"
    if r.status_code != 200:
        return f"docling-Probe: HTTP {r.status_code} {r.text[:120]}"
    try:
        d = r.json()
    except ValueError:
        return "docling-Probe: Antwort ohne JSON"
    md = (d.get("document") or {}).get("md_content") or ""
    if d.get("status") not in ("success", "partial_success") or PROBE_MERKWORT not in md:
        return f"docling-Probe: status {d.get('status')}, Merkwort {'ja' if PROBE_MERKWORT in md else 'nein'}"
    return None


def job_zurueckgeben(pg_conn, job_id, grund):
    """Gibt einen Job OHNE Versuchszählung zurück in die Queue (attempts wurde
    beim Claim erhöht und wird hier wieder abgezogen)."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """UPDATE file_jobs
               SET status = 'pending', attempts = GREATEST(attempts - 1, 0),
                   last_error = %s,
                   processing_started_at = NULL, processing_heartbeat_at = NULL
               WHERE id = %s AND status = 'processing'""",
            (grund[:500], job_id),
        )
    pg_conn.commit()


def assert_job_still_valid(cur, job_id):
    """Prüft INNERHALB der laufenden Transaktion, ob der Job noch gültig ist.
    Der Scanner kann ihn zwischenzeitlich auf 'cancelled' gesetzt haben (Datei
    verschoben/gelöscht, während der Worker sie noch verarbeitete). FOR UPDATE
    sperrt die Zeile, damit sich der Status bis zum Commit nicht mehr ändert.
    Ohne diese Prüfung könnte ein überholter Job ein Dokument unter einem
    Pfad anlegen, den es gar nicht mehr gibt -- eine Karteileiche."""
    cur.execute("SELECT status FROM file_jobs WHERE id = %s FOR UPDATE", (job_id,))
    row = cur.fetchone()
    if row is None:
        raise JobCancelled(f"Job {job_id} existiert nicht mehr")
    if row[0] != "processing":
        raise JobCancelled(f"Job {job_id} wurde zwischenzeitlich auf '{row[0]}' gesetzt")


class JobCancelled(Exception):
    """Der Job wurde vom Scanner überholt (Datei verschoben/gelöscht)."""


def heartbeat(pg_conn, job_id):
    """Signalisiert, dass dieser Job noch aktiv bearbeitet wird. Wird während
    der Verarbeitung mehrfach aufgerufen (Download, Docling, Embedding-Batches),
    damit ein parallel startender Worker einen langsamen, aber lebenden Job
    nicht als abgestürzt einstuft und doppelt verarbeitet.

    Fehler hier dürfen die Verarbeitung nie abbrechen -- der Heartbeat ist
    eine Zusatzsicherung, kein kritischer Pfad."""
    if pg_conn is None:  # --simulieren
        return
    try:
        with pg_conn.cursor() as cur:
            cur.execute(
                "UPDATE file_jobs SET processing_heartbeat_at = now() WHERE id = %s",
                (job_id,),
            )
        pg_conn.commit()
    except Exception:
        try:
            pg_conn.rollback()
        except Exception:
            pass


def claim_jobs(pg_conn, limit):
    """Holt pending-Jobs und markiert sie atomar als 'processing', damit
    zwei parallel laufende Worker nicht denselben Job greifen.

    attempts wird SOFORT erhöht, nicht erst beim Abschluss: Stürzt der
    Prozess mitten in Docling/Ollama ab, würde der Zähler sonst nie steigen
    und ein dauerhaft abstürzender Job liefe endlos in Wiederholung."""
    with pg_conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """UPDATE file_jobs
               SET status = 'processing',
                   processing_started_at = now(),
                   processing_heartbeat_at = now(),
                   attempts = attempts + 1
               WHERE id IN (
                   SELECT id FROM file_jobs
                   WHERE status = 'pending'
                   ORDER BY (strpos(origin_path, '/Wissensbasis/da-agent/') > 0) DESC,
                            (strpos(origin_path, '/Verträge/') > 0) DESC,
                            (strpos(origin_path, '/Kramer Gastronomie AG/') > 0) DESC,
                            (strpos(origin_path, '/2026/') > 0
                             OR strpos(origin_path, '/2025/') > 0) DESC,
                            id
                   LIMIT %s
                   FOR UPDATE SKIP LOCKED
               )
               RETURNING id, origin_path, action, old_path""",
            (limit,),
        )
        jobs = cur.fetchall()
    pg_conn.commit()
    return jobs


def finish_job(pg_conn, job_id, status, error=None):
    """Setzt den Endstatus. 'cancelled' wird nie überschrieben -- das hat der
    Scanner gesetzt, weil die Datei zwischenzeitlich verschoben/gelöscht wurde.
    attempts wird hier NICHT erhöht, das passiert bereits beim Claim."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """UPDATE file_jobs
               SET status = %s, last_error = %s,
                   processing_started_at = NULL, processing_heartbeat_at = NULL
               WHERE id = %s AND status <> 'cancelled'""",
            (status, error, job_id),
        )
    pg_conn.commit()


def download_file(session, nextcloud_url, origin_path):
    """origin_path ist bereits der volle DAV-Pfad (dekodiert), wie ihn der
    Scanner in file_tracking geschrieben hat."""
    from urllib.parse import quote
    url = urljoin(nextcloud_url, quote(origin_path, safe="/"))
    try:
        resp = session.get(url, timeout=120)
    except requests.RequestException as exc:
        if ist_verbindung_abgewiesen(exc):
            raise DienstNichtErreichbar(f"nextcloud nicht erreichbar: {type(exc).__name__}") from exc
        raise
    if resp.status_code == 503:  # Wartungsmodus – nicht die Schuld der Datei
        raise DienstNichtErreichbar("nextcloud HTTP 503 (Wartungsmodus?)")
    if resp.status_code != 200:
        raise RuntimeError(f"Download fehlgeschlagen ({resp.status_code}) für {origin_path}")
    return resp.content


try:
    import extract_msg
    HAVE_EXTRACT_MSG = True
except ImportError:
    HAVE_EXTRACT_MSG = False


def extract_msg_text(content, filename):
    """Outlook-.msg-Dateien: Docling kann dieses Format nicht öffnen, deshalb
    hier über extract-msg. Liest Kopfdaten und Textkörper aus und formatiert
    sie wie die Markdown-Dateien aus dem PST-Import (gleiche Struktur, damit
    die Suche einheitlich funktioniert)."""
    if not HAVE_EXTRACT_MSG:
        raise RuntimeError(
            "extract-msg fehlt. Installiere mit: "
            "pip install extract-msg --break-system-packages"
        )

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".msg", delete=True) as tmp:
        tmp.write(content)
        tmp.flush()
        msg = extract_msg.Message(tmp.name)
        try:
            kopf = [
                f"# {msg.subject or '(kein Betreff)'}",
                "",
                f"**Von:** {msg.sender or 'unbekannt'}  ",
                f"**An:** {msg.to or 'unbekannt'}  ",
                f"**Datum:** {msg.date or 'unbekannt'}",
                "",
                "---",
                "",
            ]
            body = msg.body or ""
            anhaenge = [a.longFilename or a.shortFilename or "?" for a in msg.attachments]
            if anhaenge:
                kopf.append(f"*Anhänge: {', '.join(str(a) for a in anhaenge)}*")
                kopf.append("")
            return "\n".join(kopf) + body
        finally:
            msg.close()


# Alte Office-Binaerformate. Docling lehnt sie in der Stufe 'user_input' ab
# ("An unexpected error occurred while opening the document"), noch bevor eine
# Verarbeitung beginnt. LibreOffice (unoserver) konvertiert sie vorher.
#
# Bewusst nach OOXML und NICHT nach PDF: Docling liest Tabellenstrukturen aus
# xlsx/docx nativ aus. Ueber PDF muesste es sie per Heuristik rekonstruieren --
# bei Tabellen ist das der Unterschied zwischen brauchbar und zerhackt.
LEGACY_FORMATE = {
    ".doc": "docx",
    ".xls": "xlsx",
    ".ppt": "pptx",
    ".rtf": "docx",
}

# Konvertierung ist reine CPU-Arbeit ohne OCR und dauert normal 1-3 Sekunden.
# Grosszuegig bemessen fuer den Fall, dass mehrere Worker gleichzeitig anfragen
# -- unoserver arbeitet Anfragen seriell ab.
UNOSERVER_TIMEOUT = 300


def convert_legacy(unoserver_url, filename, content):
    """Wandelt ein altes Office-Binaerformat in sein OOXML-Gegenstueck um.

    Gibt (neuer_dateiname, neuer_inhalt) zurueck. Ist die Endung kein
    Altformat, kommen Name und Inhalt unveraendert zurueck -- der Aufrufer
    muss also nicht selbst pruefen.
    """
    basis, punkt, rohe_endung = filename.rpartition(".")
    if not punkt:
        return filename, content
    ziel_format = LEGACY_FORMATE.get("." + rohe_endung.lower())
    if not ziel_format:
        return filename, content

    try:
        resp = http("libreoffice", "POST",
            urljoin(unoserver_url, "/request"),
            files={"file": (filename, content)},
            data={"convert-to": ziel_format},
            timeout=UNOSERVER_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"LibreOffice nicht erreichbar ({unoserver_url}): {exc}"
        ) from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"LibreOffice-Fehler ({resp.status_code}) bei {endung}: "
            f"{resp.text[:200]}"
        )

    # Leere Antwort mit Status 200 kommt vor, wenn LibreOffice die Datei zwar
    # annimmt, aber nichts erzeugt (kaputte oder passwortgeschuetzte Datei).
    # Ohne diese Pruefung liefe eine 0-Byte-Datei weiter an Docling und
    # scheiterte dort mit einer irrefuehrenden Meldung.
    if not resp.content:
        raise RuntimeError(
            f"LibreOffice lieferte leeres Ergebnis fuer {filename} "
            f"(Datei vermutlich beschaedigt oder passwortgeschuetzt)"
        )

    return basis + "." + ziel_format, resp.content


def extract_text(docling_url, unoserver_url, filename, content):
    """Schickt die Datei an Docling und gibt den extrahierten Markdown-Text zurück.
    Ausnahmen: .msg (Outlook) läuft über extract-msg, alte Office-Binärformate
    (.doc/.xls/.ppt/.rtf) werden vorher über LibreOffice nach OOXML gewandelt."""
    if filename.lower().endswith(".msg"):
        return extract_msg_text(content, filename)

    filename, content = convert_legacy(unoserver_url, filename, content)

    files = {"files": (filename, content)}
    resp = http("docling", "POST",
        urljoin(docling_url, "/v1/convert/file"),
        files=files, data=DOCLING_FELDER, timeout=600,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Docling-Fehler ({resp.status_code}): {resp.text[:300]}")

    result = resp.json()
    if result.get("status") not in ("success", "partial_success"):
        errs = result.get("errors") or []
        raise RuntimeError(f"Docling-Status '{result.get('status')}': {str(errs)[:300]}")

    return (result.get("document") or {}).get("md_content") or ""


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Teilt den Text in überlappende Stücke. Bevorzugt Absatz-/Satzgrenzen,
    damit ein Chunk nicht mitten im Wort endet."""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Rückwärts nach einer sauberen Trennstelle suchen
            window = text[start:end]
            for sep in ("\n\n", "\n", ". ", " "):
                pos = window.rfind(sep)
                if pos > size * 0.5:  # nur akzeptieren, wenn nicht zu weit vorne
                    end = start + pos + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def embed_batch(ollama_url, texts, model="bge-m3"):
    """Erzeugt Embeddings für mehrere Chunks in einem Aufruf."""
    resp = http("ollama", "POST",
        urljoin(ollama_url, "/api/embed"),
        json={"model": model, "input": texts},
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama-Fehler ({resp.status_code}): {resp.text[:300]}")
    embeddings = resp.json().get("embeddings")
    if not embeddings or len(embeddings) != len(texts):
        raise RuntimeError(f"Ollama lieferte {len(embeddings or [])} Embeddings für {len(texts)} Chunks")
    # Die chunks-Tabelle ist auf vector(1024) festgelegt -- ein anderes Modell
    # würde bei jedem Insert scheitern, deshalb hier früh und deutlich melden
    if len(embeddings[0]) != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding hat {len(embeddings[0])} Dimensionen, erwartet {EMBEDDING_DIM}. "
            f"Falsches Modell? (konfiguriert: '{model}')"
        )
    return embeddings


def guess_source(origin_path):
    """Leitet aus dem Pfad ab, ob es sich um KGAG- oder private Unterlagen handelt."""
    lowered = origin_path.lower()
    if "kramer gastronomie" in lowered:
        return "kgag"
    if any(x in lowered for x in ("hockey club davos", "hotelfachschule", "david augustin")):
        return "privat"
    return "unklar"


def store_document(pg_conn, job_id, origin_path, filename, content_hash, chunks, embeddings):
    """Schreibt Dokument + Chunks. Bestehende Chunks werden vorher entfernt
    (Upsert), damit bei einer Neuverarbeitung keine Karteileichen bleiben."""
    with pg_conn.cursor() as cur:
        assert_job_still_valid(cur, job_id)
        cur.execute(
            """INSERT INTO documents
               (origin_type, origin_path, filename, content_hash, source, indexed_at)
               VALUES ('nextcloud_file', %s, %s, %s, %s, now())
               ON CONFLICT (origin_type, origin_path) DO UPDATE SET
                 filename = EXCLUDED.filename,
                 content_hash = EXCLUDED.content_hash,
                 source = EXCLUDED.source,
                 updated_at = now()
               RETURNING id""",
            (origin_path, filename, content_hash, guess_source(origin_path)),
        )
        document_id = cur.fetchone()[0]

        cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))

        if chunks:
            execute_values(
                cur,
                """INSERT INTO chunks (document_id, chunk_index, content, embedding)
                   VALUES %s""",
                [
                    (document_id, i, chunk, "[" + ",".join(map(str, emb)) + "]")
                    for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
                ],
                template="(%s, %s, %s, %s::vector)",
                page_size=100,
            )

        cur.execute(
            """UPDATE file_tracking
               SET index_status = 'indexed', indexed_at = now(), content_sha256 = %s
               WHERE origin_path = %s""",
            (content_hash, origin_path),
        )
    pg_conn.commit()
    return document_id


def handle_delete(pg_conn, job_id, origin_path):
    with pg_conn.cursor() as cur:
        assert_job_still_valid(cur, job_id)
        cur.execute(
            "DELETE FROM documents WHERE origin_type = 'nextcloud_file' AND origin_path = %s",
            (origin_path,),
        )
        removed = cur.rowcount
    pg_conn.commit()
    return removed


def handle_move(pg_conn, job_id, new_path, old_path):
    """Nur den Pfad umschreiben -- Inhalt und Embeddings bleiben gültig."""
    with pg_conn.cursor() as cur:
        assert_job_still_valid(cur, job_id)

        # Erst prüfen, ob der alte Datensatz überhaupt existiert. Vorschnelles
        # Löschen am Ziel würde sonst ein gültiges Dokument vernichten, obwohl
        # es gar nichts zu verschieben gibt.
        cur.execute(
            "SELECT id FROM documents WHERE origin_type = 'nextcloud_file' AND origin_path = %s",
            (old_path,),
        )
        alt = cur.fetchone()
        if not alt:
            return 0  # nichts zu verschieben -> Aufrufer behandelt es als 'created'

        # Nur jetzt einen etwaigen Alt-Eintrag am Zielpfad entfernen: er stammt
        # aus einer früheren, inkonsistenten Verarbeitung und würde sonst die
        # UNIQUE-Constraint beim UPDATE verletzen.
        cur.execute(
            """DELETE FROM documents
               WHERE origin_type = 'nextcloud_file' AND origin_path = %s AND id <> %s""",
            (new_path, alt[0]),
        )
        cur.execute(
            """UPDATE documents SET origin_path = %s, filename = %s, updated_at = now()
               WHERE id = %s""",
            (new_path, new_path.rstrip("/").split("/")[-1], alt[0]),
        )
        moved = cur.rowcount
        cur.execute(
            "UPDATE file_tracking SET index_status = 'indexed' WHERE origin_path = %s",
            (new_path,),
        )
    pg_conn.commit()
    return moved


def process_one(job, session, args, pg_conn, simulieren=False):
    """simulieren=True: alles bis und mit Embedding, aber nichts speichern
    (pg_conn ist dann None, auch kein Heartbeat)."""
    action = job["action"]
    path = job["origin_path"]
    job_id = job["id"]
    filename = path.rstrip("/").split("/")[-1]

    if simulieren and action in ("deleted", "moved"):
        return f"Simulation: Aktion '{action}' uebersprungen (nur Datenbank)"

    if action == "deleted":
        removed = handle_delete(pg_conn, job_id, path)
        return f"gelöscht ({removed} Dokument(e) entfernt)"

    if action == "moved":
        moved = handle_move(pg_conn, job_id, path, job["old_path"])
        if moved == 0:
            # Alter Pfad war nie indexiert -> wie eine neue Datei behandeln
            action = "created"
        else:
            return f"verschoben (Pfad aktualisiert)"

    content = download_file(session, args.nextcloud_url, path)
    if len(content) > MAX_FILE_SIZE:
        raise RuntimeError(f"Datei zu gross ({len(content) // 1024 // 1024} MB, Limit {MAX_FILE_SIZE // 1024 // 1024} MB)")
    heartbeat(pg_conn, job_id)  # Download geschafft

    content_hash = hashlib.sha256(content).hexdigest()
    text = extract_text(args.docling_url, args.unoserver_url, filename, content)
    heartbeat(pg_conn, job_id)  # Textextraktion geschafft (kann bis 10 Min dauern)

    chunks = chunk_text(text)

    if not chunks:
        # Kein verwertbarer Text (leere Datei, reines Bild ohne erkennbaren Text)
        if not simulieren:
            store_document(pg_conn, job_id, path, filename, content_hash, [], [])
        return "kein Text extrahierbar (0 Chunks)"

    embeddings = []
    batch = 32  # mehr Chunks pro Ollama-Aufruf wären speicherhungrig
    for i in range(0, len(chunks), batch):
        embeddings.extend(embed_batch(args.ollama_url, chunks[i:i + batch]))
        heartbeat(pg_conn, job_id)  # bei vielen Chunks laufen hier viele Runden

    if not simulieren:
        store_document(pg_conn, job_id, path, filename, content_hash, chunks, embeddings)
    return f"{len(chunks)} Chunks, {len(text)} Zeichen"


def recover_stale_jobs(pg_conn, stale_minutes=60, max_attempts=3):
    """Setzt Jobs zurück, die hängen geblieben sind (Worker abgestürzt), und
    gibt fehlgeschlagenen Jobs eine begrenzte Zahl neuer Versuche.

    Massgeblich ist das letzte Lebenszeichen (processing_heartbeat_at), nicht
    die Startzeit: Ein Job darf legitim lange laufen -- Docling wartet bis zu
    10 Minuten, danach folgen bei grossen Dateien viele Embedding-Runden. Nur
    wenn seit stale_minutes GAR KEIN Lebenszeichen mehr kam, ist der Worker
    tatsächlich abgestürzt. COALESCE fängt Alt-Jobs ohne Heartbeat ab."""
    stale_bedingung = """
        status = 'processing'
        AND COALESCE(processing_heartbeat_at, processing_started_at) IS NOT NULL
        AND COALESCE(processing_heartbeat_at, processing_started_at)
            < now() - (%s || ' minutes')::interval
    """

    with pg_conn.cursor() as cur:
        cur.execute(
            f"""UPDATE file_jobs
                SET status = 'pending', processing_started_at = NULL,
                    processing_heartbeat_at = NULL,
                    last_error = 'Worker abgebrochen, zurueckgesetzt'
                WHERE {stale_bedingung} AND attempts < %s""",
            (stale_minutes, max_attempts),
        )
        stale = cur.rowcount

        # Hängengebliebene Jobs, die ihr Versuchslimit erreicht haben, endgültig
        # als fehlgeschlagen markieren statt endlos zu wiederholen
        cur.execute(
            f"""UPDATE file_jobs
                SET status = 'failed', processing_started_at = NULL,
                    processing_heartbeat_at = NULL,
                    last_error = 'Nach mehreren Abbruechen aufgegeben'
                WHERE {stale_bedingung} AND attempts >= %s""",
            (stale_minutes, max_attempts),
        )
        aufgegeben = cur.rowcount

        cur.execute(
            """UPDATE file_jobs
               SET status = 'pending', processing_started_at = NULL,
                   processing_heartbeat_at = NULL
               WHERE status = 'failed' AND attempts < %s""",
            (max_attempts,),
        )
        retried = cur.rowcount
    pg_conn.commit()
    return stale, retried, aufgegeben


def verarbeite_job_isoliert(job, args, pg_params, zaehler, lock, stopp=None):
    """Läuft in einem eigenen Thread. Wichtig: eigene DB-Verbindung und eigene
    HTTP-Session pro Thread -- psycopg2-Verbindungen sind nicht threadsicher,
    eine geteilte Verbindung würde zu vermischten Transaktionen führen.
    stopp (threading.Event) wird gesetzt, wenn ein Dienst nicht erreichbar ist."""
    session = requests.Session()
    session.auth = (args.nextcloud_user, args.nextcloud_password)

    conn = None
    started = time.time()
    short = job["origin_path"].rstrip("/").split("/")[-1]

    try:
        conn = psycopg2.connect(**pg_params)
        info = process_one(job, session, args, conn)
        finish_job(conn, job["id"], "done")
        with lock:
            zaehler["ok"] += 1
        print(f"  OK   [{job['action']:8s}] {short[:60]:60s} {info} "
              f"({time.time() - started:.1f}s)", flush=True)

    except DienstNichtErreichbar as e:
        if stopp is not None:
            stopp.set()
        if conn:
            conn.rollback()
            try:
                job_zurueckgeben(conn, job["id"], f"Zurueckgegeben (ohne Versuch): {e}")
            except Exception:
                pass  # bleibt 'processing', recover_stale_jobs holt ihn zurueck
        with lock:
            zaehler["zurueck"] = zaehler.get("zurueck", 0) + 1
        print(f"  ZURUECK [{job['action']:8s}] {short[:60]:60s} {e}", flush=True)

    except JobCancelled as e:
        if conn:
            conn.rollback()
        with lock:
            zaehler["cancelled"] += 1
        print(f"  UEBERHOLT [{job['action']:8s}] {short[:60]:60s} {e}", flush=True)

    except Exception as e:
        if conn:
            conn.rollback()
            try:
                finish_job(conn, job["id"], "failed", str(e)[:500])
            except Exception:
                pass
        with lock:
            zaehler["fail"] += 1
        print(f"  FEHL [{job['action']:8s}] {short[:60]:60s} {str(e)[:150]}", flush=True)

    finally:
        session.close()
        if conn:
            conn.close()


def endung_von(pfad):
    m = re.search(r"\.([A-Za-z0-9]{1,5})$", pfad)
    return m.group(1).lower() if m else "(ohne)"


def ohne_namen(text, pfad):
    """Fehlertext ohne Pfad und Dateinamen (Ausgabe der Simulation)."""
    name = pfad.rstrip("/").split("/")[-1]
    for teil in (pfad, name):
        if teil:
            text = text.replace(teil, "<DATEI>")
    return re.sub(r"[^\s'\"(),:;]+\.[A-Za-z0-9]{2,5}\b", "<DATEI>", text)


def simulation(args, pg_params):
    """--simulieren: Gesundheitsprüfung, Probe und die genannten Jobs ohne
    jede Schreiboperation (kein Claim, kein Heartbeat, kein Speichern)."""
    probleme = dienste_pruefen(args)
    print(f"Gesundheitspruefung: {'OK' if not probleme else '; '.join(probleme)}")
    probe = None if probleme else docling_probe(args)
    if not probleme:
        print(f"docling-Probe: {'OK' if probe is None else probe}")
    if probleme or probe:
        print("Ergebnis: Lauf wuerde ohne Claim enden (kein Job, kein Versuch gezaehlt).")
        return 3
    ids = [int(x) for x in args.job_ids.split(",") if x.strip()]
    with psycopg2.connect(**pg_params) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, origin_path, action, old_path FROM file_jobs WHERE id = ANY(%s) ORDER BY id", (ids,))
        jobs = cur.fetchall()
    session = requests.Session()
    session.auth = (args.nextcloud_user, args.nextcloud_password)
    zaehler = {"OK": 0, "FEHL": 0, "ZURUECK": 0}
    for job in jobs:
        t = time.time()
        try:
            info = process_one(job, session, args, None, simulieren=True)
            art = "OK"
        except DienstNichtErreichbar as e:
            info, art = f"{e} -> Job ginge ohne Versuch zurueck, Lauf endet", "ZURUECK"
        except Exception as e:
            info, art = ohne_namen(str(e), job["origin_path"])[:160], "FEHL"
        zaehler[art] += 1
        print(f"  {art:7s} id={job['id']} .{endung_von(job['origin_path']):5s} {info} ({time.time() - t:.1f}s)", flush=True)
    print(f"Simulation: {len(jobs)} Jobs – " + ", ".join(f"{k} {v}" for k, v in zaehler.items()))
    return 0


def positiv(minimum, maximum, name):
    """Erzeugt einen argparse-Typ, der nur Werte im erlaubten Bereich zulässt.
    Ohne diese Prüfung könnte ein negatives --limit in Postgres zu einem
    faktisch unbegrenzten LIMIT werden."""
    def pruefen(wert):
        try:
            zahl = int(wert)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{name} muss eine ganze Zahl sein")
        if not minimum <= zahl <= maximum:
            raise argparse.ArgumentTypeError(
                f"{name} muss zwischen {minimum} und {maximum} liegen (war: {zahl})"
            )
        return zahl
    return pruefen


def main():
    parser = argparse.ArgumentParser(description="Arbeitet die file_jobs-Queue ab")
    parser.add_argument("--nextcloud-url", required=True)
    parser.add_argument("--nextcloud-user", required=True)
    parser.add_argument("--nextcloud-password", required=True)
    parser.add_argument("--docling-url", required=True)
    parser.add_argument("--unoserver-url", default="http://100.93.33.0:2004",
                        help="LibreOffice/unoserver für alte Office-Binärformate")
    parser.add_argument("--ollama-url", required=True)
    parser.add_argument("--pg-host", required=True)
    parser.add_argument("--pg-port", default="5432")
    parser.add_argument("--pg-db", required=True)
    parser.add_argument("--pg-user", required=True)
    parser.add_argument("--pg-password", required=True)
    parser.add_argument("--limit", type=positiv(0, 100000, "--limit"), default=50,
                        help="Maximale Anzahl Jobs pro Lauf (0 = alle)")
    parser.add_argument("--stale-minutes", type=positiv(1, 1440, "--stale-minutes"), default=20,
                        help="Nach wie vielen Minuten OHNE LEBENSZEICHEN ein "
                             "'processing'-Job als abgestuerzt gilt. Dank Heartbeat "
                             "reichen 20 Minuten -- lange laufende Jobs melden sich "
                             "waehrend der Verarbeitung regelmaessig.")
    parser.add_argument("--max-attempts", type=positiv(1, 20, "--max-attempts"), default=3,
                        help="Wie oft ein fehlgeschlagener Job erneut versucht wird")
    parser.add_argument("--parallel", type=positiv(1, 32, "--parallel"), default=4,
                        help="Anzahl paralleler Threads (Standard 4). Die Arbeit "
                             "besteht überwiegend aus Warten auf Docling/Ollama, "
                             "deshalb bringt Parallelität hier viel.")
    parser.add_argument("--simulieren", action="store_true",
                        help="Nur mit --job-ids: verarbeiten ohne Speichern/Statusaenderung")
    parser.add_argument("--job-ids", default="",
                        help="Kommagetrennte Job-IDs fuer --simulieren")
    args = parser.parse_args()
    if args.simulieren and not args.job_ids:
        parser.error("--simulieren braucht --job-ids")

    pg_params = {
        "host": args.pg_host, "port": args.pg_port,
        "dbname": args.pg_db, "user": args.pg_user, "password": args.pg_password,
    }

    if args.simulieren:
        return simulation(args, pg_params)

    # Vor jedem Zugriff auf die Queue: Dienste bereit? Sonst ohne Claim enden.
    probleme = dienste_pruefen(args)
    grund = "; ".join(probleme) if probleme else docling_probe(args)
    if grund:
        print(f"ABBRUCH vor dem ersten Job: {grund}. Kein Job uebernommen.", flush=True)
        return 3

    # Eigene Verbindung nur für Claiming und Recovery -- die Worker-Threads
    # bauen sich jeweils ihre eigene auf
    pg_conn = psycopg2.connect(**pg_params)

    zaehler = {"ok": 0, "fail": 0, "cancelled": 0, "zurueck": 0}
    lock = threading.Lock()
    stopp = threading.Event()
    abbruch = None

    try:
        stale, retried, aufgegeben = recover_stale_jobs(pg_conn, args.stale_minutes, args.max_attempts)
        if stale or retried or aufgegeben:
            print(f"Recovery: {stale} abgebrochene Jobs zurueckgesetzt, "
                  f"{retried} fehlgeschlagene erneut eingereiht, "
                  f"{aufgegeben} endgueltig aufgegeben.\n")

        print(f"Verarbeite mit {args.parallel} parallelen Threads.\n", flush=True)
        lauf_start = time.time()

        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            verbleibend = args.limit if args.limit else None
            while True:
                # Gesundheitsprüfung vor jeder Runde (Runde = --parallel Jobs)
                if stopp.is_set():
                    abbruch = "Dienst waehrend der Verarbeitung nicht erreichbar"
                    break
                probleme = dienste_pruefen(args)
                if probleme:
                    abbruch = "; ".join(probleme)
                    break
                # Nie mehr claimen als die Threads in einer Runde abarbeiten --
                # sonst stünden Jobs minutenlang auf 'processing', ohne dass
                # jemand daran arbeitet (und blockierten die Stale-Erkennung)
                batch_size = args.parallel
                if verbleibend is not None:
                    batch_size = min(batch_size, verbleibend)
                    if batch_size <= 0:
                        break

                jobs = claim_jobs(pg_conn, batch_size)
                if not jobs:
                    break

                futures = [
                    pool.submit(verarbeite_job_isoliert, job, args, pg_params, zaehler, lock, stopp)
                    for job in jobs
                ]
                for f in as_completed(futures):
                    f.result()  # Ausnahmen sind bereits im Thread behandelt

                if verbleibend is not None:
                    verbleibend -= len(jobs)

        dauer = time.time() - lauf_start
        erledigt = zaehler["ok"] + zaehler["fail"]
        if erledigt:
            print(f"\nDurchsatz: {erledigt / dauer * 60:.1f} Dateien/Minute "
                  f"({dauer:.0f}s für {erledigt} Dateien)")
    finally:
        pg_conn.close()

    print(f"\nFertig: {zaehler['ok']} erfolgreich, {zaehler['fail']} fehlgeschlagen, "
          f"{zaehler['cancelled']} ueberholt (Datei zwischenzeitlich verschoben/geloescht), "
          f"{zaehler['zurueck']} ohne Versuch zurueckgegeben.")
    if abbruch:
        print(f"ABBRUCH: {abbruch}. Lauf beendet, restliche Jobs bleiben pending.", flush=True)
        return 3
    return 1 if zaehler["fail"] and not zaehler["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
