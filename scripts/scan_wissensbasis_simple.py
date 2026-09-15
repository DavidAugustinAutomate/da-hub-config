#!/usr/bin/env python3
"""
scan_wissensbasis_simple.py

Vereinfachter inkrementeller Scanner. Kein ETag-Baum-Pruning (unnötig bei
~659 Ordnern) -- jeder Lauf listet den kompletten Baum neu (iterativ,
Depth:1 pro Ordner, wie das bereits bewiesen funktionierende
scan_wissensbasis.py) und ermittelt Änderungen per einfachem SQL-Vergleich
gegen den letzten bekannten Stand.

Erkennt:
- CREATED: Pfad ist neu
- MODIFIED: Pfad bekannt, ETag hat sich geändert
- DELETED: Pfad war bekannt, taucht in diesem Lauf nicht mehr auf
- MOVED: gleiche nextcloud_file_id, anderer Pfad

Aufruf:
    python3 scan_wissensbasis_simple.py \
        --nextcloud-url http://100.93.33.0:8080 \
        --nextcloud-user wissensbasis-bot \
        --nextcloud-password '<APP-PASSWORT>' \
        --root-path /Wissensbasis \
        --pg-host 100.93.33.0 --pg-port 5432 \
        --pg-db knowledge --pg-user dahub --pg-password '<PG-PASSWORT>'
"""

import argparse
import sys
import time
import xml.etree.ElementTree as ET
from collections import deque
from urllib.parse import quote, unquote, urljoin

import requests

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("FEHLER: psycopg2 fehlt. Installiere mit:")
    print("  pip install psycopg2-binary --break-system-packages")
    sys.exit(1)


DAV_NS = "{DAV:}"
OC_NS = "{http://owncloud.org/ns}"

# Nur diese Endungen erzeugen Verarbeitungs-Jobs. Alles andere (Videos,
# Archive, Systemdateien) wird zwar in file_tracking geführt, aber nicht
# zur Textextraktion/Embedding geschickt -- spart Docling- und Ollama-Zeit.
INDEXABLE_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".txt", ".md", ".rtf", ".odt", ".ods", ".odp", ".csv",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",  # via OCR
    ".html", ".htm", ".eml", ".msg",
}

# Diese Dateien werden komplett ignoriert (kein Tracking, kein Job)
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".nomedia"}


def is_indexable(path):
    """Soll für diese Datei ein Verarbeitungs-Job erzeugt werden?"""
    name = path.rstrip("/").split("/")[-1]
    if name in IGNORED_NAMES or name.startswith("~$"):
        return False
    dot = name.rfind(".")
    if dot == -1:
        return False
    return name[dot:].lower() in INDEXABLE_EXTENSIONS


def propfind(session, url, depth="1", max_retries=3):
    """PROPFIND mit Retry bei transienten Fehlern (Netzwerk, 5xx, 429).
    Bei dauerhaften Fehlern (404, 403, 401) wird sofort abgebrochen --
    ein Retry würde dort nichts bringen."""
    headers = {"Depth": depth, "Content-Type": "application/xml"}
    body = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:prop>
    <d:resourcetype/>
    <d:getlastmodified/>
    <d:getetag/>
    <d:getcontentlength/>
    <oc:fileid/>
  </d:prop>
</d:propfind>"""

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = session.request("PROPFIND", url, headers=headers, data=body, timeout=30)
            if resp.status_code == 207:
                return resp.text
            # 5xx und 429 sind ggf. vorübergehend -> erneut versuchen
            if resp.status_code >= 500 or resp.status_code == 429:
                last_error = f"HTTP {resp.status_code}"
            else:
                raise RuntimeError(
                    f"PROPFIND fehlgeschlagen ({resp.status_code}) für {url}: {resp.text[:200]}"
                )
        except requests.exceptions.RequestException as e:
            last_error = str(e)  # Timeout, Verbindungsabbruch etc. -> erneut versuchen

        if attempt < max_retries - 1:
            wait = 2 ** attempt  # 1s, 2s, 4s
            print(f"  Warnung: {last_error} bei {url} -- erneuter Versuch in {wait}s "
                  f"({attempt + 2}/{max_retries})", flush=True)
            time.sleep(wait)

    raise RuntimeError(f"PROPFIND nach {max_retries} Versuchen fehlgeschlagen für {url}: {last_error}")


def parse_multistatus(xml_text, base_raw_href):
    """Vergleich für 'ist das der Ordner selbst' erfolgt auf Basis der rohen
    (URL-kodierten) hrefs, damit Kodierungs-Mismatches (Leerzeichen vs %20)
    keine Selbst-Erkennung verhindern."""
    root = ET.fromstring(xml_text)
    entries = []

    for response in root.findall(f"{DAV_NS}response"):
        href_el = response.find(f"{DAV_NS}href")
        if href_el is None:
            continue
        raw_href = href_el.text

        if raw_href.rstrip("/") == base_raw_href.rstrip("/"):
            continue  # der Ordner selbst, nicht sein Inhalt

        propstat_200 = None
        for propstat in response.findall(f"{DAV_NS}propstat"):
            status_el = propstat.find(f"{DAV_NS}status")
            if status_el is None or not status_el.text:
                continue
            # Format: "HTTP/1.1 200 OK" -- Statuscode exakt prüfen,
            # nicht per Substring (sonst würde z.B. "1200" auch matchen)
            parts = status_el.text.split()
            if len(parts) >= 2 and parts[1] == "200":
                propstat_200 = propstat
                break
        if propstat_200 is None:
            continue  # keine erfolgreiche propstat für diese Ressource -- überspringen
        prop = propstat_200.find(f"{DAV_NS}prop")
        if prop is None:
            continue

        resourcetype = prop.find(f"{DAV_NS}resourcetype")
        is_folder = resourcetype is not None and resourcetype.find(f"{DAV_NS}collection") is not None

        lastmod_el = prop.find(f"{DAV_NS}getlastmodified")
        last_modified = lastmod_el.text if lastmod_el is not None else None

        etag_el = prop.find(f"{DAV_NS}getetag")
        etag = etag_el.text.strip('"') if etag_el is not None and etag_el.text else None

        size_el = prop.find(f"{DAV_NS}getcontentlength")
        size = int(size_el.text) if size_el is not None and size_el.text else None

        fileid_el = prop.find(f"{OC_NS}fileid")
        file_id = fileid_el.text if fileid_el is not None else None

        entries.append({
            "raw_href": raw_href,
            "path": unquote(raw_href),
            "is_folder": is_folder,
            "last_modified": last_modified,
            "etag": etag,
            "size": size,
            "file_id": file_id,
        })

    return entries


def crawl_full_tree(session, base_url, root_raw_href):
    """Listet den kompletten Baum, iterativ (BFS-Warteschlange), keine
    Optimierung/Pruning. Gibt Liste aller gefundenen Dateien zurück."""
    queue = deque([root_raw_href])
    files = []
    folder_count = 0

    while queue:
        current_raw_href = queue.popleft()
        url = urljoin(base_url, current_raw_href)
        xml_text = propfind(session, url, depth="1")
        folder_count += 1

        entries = parse_multistatus(xml_text, current_raw_href)
        for entry in entries:
            if entry["is_folder"]:
                queue.append(entry["raw_href"])
            else:
                files.append(entry)

        if folder_count % 50 == 0:
            print(f"... {folder_count} Ordner durchsucht, {len(files)} Dateien gefunden bisher", flush=True)

    return files, folder_count


def diff_and_apply(pg_conn, current_files):
    """Vergleicht den aktuellen Baum-Zustand gegen file_tracking, schreibt
    Änderungen als file_jobs, aktualisiert file_tracking."""
    stats = {"created": 0, "modified": 0, "deleted": 0, "moved": 0, "skipped": 0}

    with pg_conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT origin_path, nextcloud_file_id, nextcloud_etag FROM file_tracking")
        known_by_path = {row["origin_path"]: row for row in cur.fetchall()}
        known_by_fileid = {row["nextcloud_file_id"]: row for row in known_by_path.values() if row["nextcloud_file_id"]}

    cur = pg_conn.cursor()
    # Erst ALLE aktuellen Pfade sammeln, bevor wir vergleichen -- sonst kann
    # die Move-Erkennung nicht unterscheiden, ob der alte Pfad noch existiert
    # (= Kopie) oder wirklich weg ist (= echter Move).
    current_paths = {f["path"] for f in current_files}
    moved_old_paths = set()
    unchanged_paths = []

    for f in current_files:
        path = f["path"]
        known = known_by_path.get(path)

        if known is None:
            moved_from = known_by_fileid.get(f["file_id"]) if f["file_id"] else None
            # Nur ein echter Move, wenn der alte Pfad im aktuellen Baum nicht
            # mehr vorkommt -- sonst wurde die Datei kopiert, nicht verschoben
            if (moved_from
                    and moved_from["origin_path"] != path
                    and moved_from["origin_path"] not in current_paths):
                moved_old_paths.add(moved_from["origin_path"])
                # Offene Jobs für den alten Pfad entwerten -- NICHT löschen:
                # ein Worker könnte den Job bereits geladen haben und würde
                # sonst unbemerkt weiterarbeiten. 'cancelled' bleibt sichtbar,
                # der Worker prüft es vor jedem Schreibvorgang.
                cur.execute(
                    """UPDATE file_jobs SET status = 'cancelled',
                       last_error = 'Datei wurde verschoben -- Job ueberholt'
                       WHERE origin_path = %s AND status IN ('pending', 'processing')""",
                    (moved_from["origin_path"],),
                )
                cur.execute(
                    """INSERT INTO file_jobs (origin_path, action, old_path)
                       VALUES (%s, 'moved', %s)
                       ON CONFLICT (origin_path, action) WHERE status IN ('pending','processing')
                       DO NOTHING""",
                    (path, moved_from["origin_path"]),
                )
                if cur.rowcount == 1:
                    stats["moved"] += 1
                cur.execute(
                    """UPDATE file_tracking SET origin_path = %s, nextcloud_etag = %s,
                       last_modified = %s, file_size = %s, last_scanned_at = now(),
                       index_status = 'pending'
                       WHERE nextcloud_file_id = %s""",
                    (path, f["etag"], f["last_modified"], f["size"], f["file_id"]),
                )
            else:
                if is_indexable(path):
                    cur.execute(
                        """INSERT INTO file_jobs (origin_path, action)
                           VALUES (%s, 'created')
                           ON CONFLICT (origin_path, action) WHERE status IN ('pending','processing')
                           DO NOTHING""",
                        (path,),
                    )
                    if cur.rowcount == 1:
                        stats["created"] += 1
                    new_status = "pending"
                else:
                    stats["skipped"] += 1
                    new_status = "skipped"
                cur.execute(
                    """INSERT INTO file_tracking
                       (origin_path, nextcloud_file_id, nextcloud_etag, last_modified,
                        file_size, last_scanned_at, index_status)
                       VALUES (%s, %s, %s, %s, %s, now(), %s)
                       ON CONFLICT (origin_path) DO UPDATE SET
                         nextcloud_file_id = EXCLUDED.nextcloud_file_id,
                         nextcloud_etag = EXCLUDED.nextcloud_etag,
                         last_modified = EXCLUDED.last_modified,
                         file_size = EXCLUDED.file_size,
                         last_scanned_at = now(),
                         index_status = EXCLUDED.index_status""",
                    (path, f["file_id"], f["etag"], f["last_modified"], f["size"], new_status),
                )

        elif known["nextcloud_etag"] != f["etag"]:
            if is_indexable(path):
                cur.execute(
                    """INSERT INTO file_jobs (origin_path, action)
                       VALUES (%s, 'modified')
                       ON CONFLICT (origin_path, action) WHERE status IN ('pending','processing')
                       DO NOTHING""",
                    (path,),
                )
                if cur.rowcount == 1:
                    stats["modified"] += 1
                new_status = "pending"
            else:
                stats["skipped"] += 1
                new_status = "skipped"
            cur.execute(
                """UPDATE file_tracking SET nextcloud_etag = %s, last_modified = %s,
                   file_size = %s, last_scanned_at = now(), index_status = %s
                   WHERE origin_path = %s""",
                (f["etag"], f["last_modified"], f["size"], new_status, path),
            )
        else:
            # Unverändert -- sammeln und am Ende in wenigen Batches aktualisieren
            # statt 250'000 einzelne DB-Anfragen abzusetzen
            unchanged_paths.append(path)

    # Unveränderte Dateien in Batches aktualisieren (statt 1 Anfrage pro Datei) --
    # betrifft typischerweise >99% aller Dateien, deshalb der grösste Zeitfaktor
    if unchanged_paths:
        print(f"Aktualisiere {len(unchanged_paths)} unveränderte Dateien in Batches...", flush=True)
        batch_size = 5000
        for i in range(0, len(unchanged_paths), batch_size):
            cur.execute(
                "UPDATE file_tracking SET last_scanned_at = now() WHERE origin_path = ANY(%s)",
                (unchanged_paths[i:i + batch_size],),
            )

    # Löschungen: bekannte Pfade, die im aktuellen Baum nicht mehr auftauchen.
    # Sicherheitshinweis: Diese Logik läuft nur, wenn crawl_full_tree() zuvor
    # VOLLSTÄNDIG und ohne Fehler durchgelaufen ist (siehe main() -- ein
    # Fehler beim PROPFIND wirft eine Exception, die diesen Code nie erreicht).
    # Ein "leiser", fehlerfrei zurückgegebener aber unvollständiger Baum
    # (z.B. durch serverseitige Rechte-Änderungen) würde dennoch fälschlich
    # als Löschung interpretiert -- bewusst in Kauf genommenes Restrisiko bei
    # diesem einfachen Ansatz, siehe Anleitung für Details.
    deleted_paths = set(known_by_path.keys()) - current_paths - moved_old_paths

    # Sicherheitsnetz: Würde dieser Lauf einen unplausibel grossen Anteil aller
    # bekannten Dateien löschen, bricht er lieber ab. Schützt vor Massenverlust
    # durch Rechte-Änderungen, falsche --root-path-Angabe oder einen Server, der
    # unvollständig aber fehlerfrei antwortet.
    if known_by_path and len(deleted_paths) > max(100, len(known_by_path) * 0.10):
        pg_conn.rollback()
        raise RuntimeError(
            f"ABBRUCH: {len(deleted_paths)} von {len(known_by_path)} bekannten Dateien "
            f"würden als gelöscht markiert (>10%). Das ist unplausibel -- vermutlich war "
            f"der Scan unvollständig (Rechte, falscher Pfad, Serverproblem). "
            f"Es wurde NICHTS verändert. Bitte prüfen und ggf. mit angepasster "
            f"Schwelle erneut ausführen."
        )

    for path in deleted_paths:
        # Offene Jobs entwerten statt löschen (siehe Kommentar beim Move-Fall)
        cur.execute(
            """UPDATE file_jobs SET status = 'cancelled',
               last_error = 'Datei wurde geloescht -- Job ueberholt'
               WHERE origin_path = %s AND status IN ('pending', 'processing')""",
            (path,),
        )
        # Job nur nötig, wenn die Datei überhaupt indexiert war -- für
        # übersprungene Dateien gibt es nichts aus pgvector zu entfernen
        if is_indexable(path):
            cur.execute(
                """INSERT INTO file_jobs (origin_path, action)
                   VALUES (%s, 'deleted')
                   ON CONFLICT (origin_path, action) WHERE status IN ('pending','processing')
                   DO NOTHING""",
                (path,),
            )
            if cur.rowcount == 1:
                stats["deleted"] += 1
        cur.execute("DELETE FROM file_tracking WHERE origin_path = %s", (path,))

    pg_conn.commit()  # eine gemeinsame Transaktion für den kompletten Diff
    cur.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Vereinfachter Änderungs-Scan der Wissensbasis")
    parser.add_argument("--nextcloud-url", required=True)
    parser.add_argument("--nextcloud-user", required=True)
    parser.add_argument("--nextcloud-password", required=True)
    parser.add_argument("--root-path", default="/Wissensbasis")
    parser.add_argument("--pg-host", required=True)
    parser.add_argument("--pg-port", default="5432")
    parser.add_argument("--pg-db", required=True)
    parser.add_argument("--pg-user", required=True)
    parser.add_argument("--pg-password", required=True)
    args = parser.parse_args()

    session = requests.Session()
    session.auth = (args.nextcloud_user, args.nextcloud_password)

    encoded_root_path = quote(args.root_path, safe="/")
    root_raw_href = f"/remote.php/dav/files/{quote(args.nextcloud_user, safe='')}{encoded_root_path}/"

    print("Durchsuche Baum...")
    files, folder_count = crawl_full_tree(session, args.nextcloud_url, root_raw_href)
    print(f"Baum-Scan fertig: {folder_count} Ordner, {len(files)} Dateien gefunden.")

    pg_conn = psycopg2.connect(
        host=args.pg_host, port=args.pg_port,
        dbname=args.pg_db, user=args.pg_user, password=args.pg_password,
    )
    try:
        print("Vergleiche gegen bekannten Stand...")
        stats = diff_and_apply(pg_conn, files)
    finally:
        pg_conn.close()

    print(f"\nFertig: {stats['created']} neu, {stats['modified']} geändert, "
          f"{stats['deleted']} gelöscht, {stats['moved']} verschoben, "
          f"{stats['skipped']} übersprungen (nicht indexierbarer Dateityp).")


if __name__ == "__main__":
    sys.exit(main())
