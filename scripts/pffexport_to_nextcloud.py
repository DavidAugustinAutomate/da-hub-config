#!/usr/bin/env python3
"""
pffexport_to_nextcloud.py

Wandelt eine von `pffexport -m items -t <ziel> <datei.pst>` erzeugte
Ordnerstruktur (ein Ordner pro Mail mit InternetHeaders.txt, Message.txt/html,
Attachments/) in Markdown-Dateien + separat gespeicherte Anhänge um,
geschrieben direkt ins Nextcloud-Datenverzeichnis.

Aufruf:
    python3 pffexport_to_nextcloud.py --input <pffexport-.export-Ordner> --output <Nextcloud-Zielordner> \
        --source privat|kgag --richtung posteingang|gesendet --granularitaet jahr|monat
"""

import argparse
import email
import hashlib
import os
import re
import shutil
import sys
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime

try:
    from bs4 import BeautifulSoup
    HAVE_BS4 = True
except ImportError:
    HAVE_BS4 = False


def slugify(text, max_len=50):
    if not text:
        return "unbekannt"
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len].strip("_") or "unbekannt"


def decode_mime_header(raw):
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded += part.decode(enc or "utf-8", errors="replace")
        else:
            decoded += part
    return decoded


def html_to_text(html):
    if HAVE_BS4:
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n")
    return re.sub(r"<[^>]+>", "", html)


def read_text_file(path):
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
        except FileNotFoundError:
            return None
    # letzter Fallback: mit Ersatzzeichen
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return None


def parse_headers(headers_path):
    """Liest InternetHeaders.txt und extrahiert Subject/From/Date."""
    raw = read_text_file(headers_path)
    if raw is None:
        return "", "", ""
    try:
        msg = email.message_from_string(raw)
        subject = decode_mime_header(msg.get("Subject", ""))
        sender = decode_mime_header(msg.get("From", ""))
        date_raw = msg.get("Date", "")
        return subject, sender, date_raw
    except Exception:
        return "", "", ""


def parse_outlook_headers(headers_path):
    """Fallback für Mails ohne InternetHeaders.txt (typisch bei Gesendet-Elementen).
    Liest OutlookHeaders.txt im 'Feldname:   Wert'-Format."""
    raw = read_text_file(headers_path)
    if raw is None:
        return "", "", ""

    fields = {}
    for line in raw.splitlines():
        m = re.match(r"^([A-Za-z][A-Za-z ]*?):\s{2,}(.*)$", line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key not in fields:
                fields[key] = val

    subject = fields.get("Subject", "")
    sender = fields.get("Sender name") or fields.get("Sent representing name") or ""
    date_field = fields.get("Client submit time") or fields.get("Delivery time") or fields.get("Creation time") or ""

    date_raw = date_field
    return subject, sender, date_raw


def parse_outlook_date(date_field):
    """Wandelt 'Sep 01, 2026 14:27:55.435541000 UTC' in ein datetime-Objekt."""
    if not date_field:
        return None
    cleaned = re.sub(r"\.\d+", "", date_field)  # Nachkommastellen der Sekunden entfernen
    cleaned = re.sub(r"\s+UTC\s*$", "", cleaned).strip()
    for fmt in ("%b %d, %Y %H:%M:%S", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def get_body(message_folder):
    """Bevorzugt Message.txt, fällt sonst auf Message.html zurück."""
    txt_path = os.path.join(message_folder, "Message.txt")
    html_path = os.path.join(message_folder, "Message.html")

    txt_content = read_text_file(txt_path)
    if txt_content and txt_content.strip():
        return txt_content.strip()

    html_content = read_text_file(html_path)
    if html_content:
        return html_to_text(html_content).strip()

    return ""


def process_message_folder(message_folder, output_dir, source_domain, richtung, failed_log, granularitaet):
    internet_headers_path = os.path.join(message_folder, "InternetHeaders.txt")
    outlook_headers_path = os.path.join(message_folder, "OutlookHeaders.txt")

    has_internet = os.path.isfile(internet_headers_path)
    has_outlook = os.path.isfile(outlook_headers_path)

    if not has_internet and not has_outlook:
        # Kein Header vorhanden -> kein verwertbares Mail-Item (z.B. Termin/Kontakt)
        return False

    dt = None

    if has_internet:
        subject, sender, date_raw = parse_headers(internet_headers_path)
        try:
            dt = parsedate_to_datetime(date_raw) if date_raw else None
        except Exception:
            dt = None

    # Fallback bzw. Ergänzung über OutlookHeaders.txt, falls InternetHeaders.txt
    # fehlt oder keine brauchbaren Werte lieferte (typisch bei Gesendet-Elementen)
    if not has_internet or not subject and not sender:
        o_subject, o_sender, o_date_raw = parse_outlook_headers(outlook_headers_path) if has_outlook else ("", "", "")
        if not has_internet:
            subject, sender, date_raw = o_subject, o_sender, o_date_raw
        else:
            subject = subject or o_subject
            sender = sender or o_sender
        if dt is None and o_date_raw:
            dt = parse_outlook_date(o_date_raw)
            if dt and not date_raw:
                date_raw = o_date_raw

    date_str = dt.strftime("%Y-%m-%d") if dt else "0000-00-00"
    year_str = dt.strftime("%Y") if dt else "0000-unbekannt"
    month_str = dt.strftime("%m") if dt else "00"

    if granularitaet == "monat":
        ziel_ordner = os.path.join(output_dir, year_str, month_str)
    else:
        ziel_ordner = os.path.join(output_dir, year_str)
    os.makedirs(ziel_ordner, exist_ok=True)

    sender_slug = slugify(sender, 30)
    subject_slug = slugify(subject, 50)
    # Hash über den Ordnerpfad selbst (stabil, eindeutig pro Mail-Item)
    short_hash = hashlib.sha256(message_folder.encode("utf-8", errors="replace")).hexdigest()[:8]
    prefix = f"{date_str}_{sender_slug}_{subject_slug}_{short_hash}"

    body = get_body(message_folder)

    attachments_dir = os.path.join(message_folder, "Attachments")
    attachment_files = []
    if os.path.isdir(attachments_dir):
        for fname in sorted(os.listdir(attachments_dir)):
            fpath = os.path.join(attachments_dir, fname)
            if os.path.isfile(fpath):
                attachment_files.append(fpath)

    md_filename = f"{prefix}.md"
    md_path = os.path.join(ziel_ordner, md_filename)

    header = (
        f"---\n"
        f"typ: email\n"
        f"quelle: {source_domain}\n"
        f"richtung: {richtung}\n"
        f"absender: {sender}\n"
        f"betreff: {subject}\n"
        f"datum: {date_raw}\n"
        f"anzahl_anhaenge: {len(attachment_files)}\n"
        f"---\n\n"
        f"# {subject}\n\n"
        f"**Von:** {sender}  \n"
        f"**Datum:** {date_raw}\n\n"
        f"---\n\n"
    )

    try:
        with open(md_path, "w", encoding="utf-8") as out:
            out.write(header + body)
    except Exception as e:
        failed_log.write(f"{message_folder}\tSchreib-Fehler (Body): {e}\n")
        return False

    for idx, att_path in enumerate(attachment_files, start=1):
        orig_name = os.path.basename(att_path)
        safe_att_name = slugify(os.path.splitext(orig_name)[0], 40)
        ext = os.path.splitext(orig_name)[1] or ""
        att_out_name = f"{prefix}_Anhang{idx}_{safe_att_name}{ext}"
        att_out_path = os.path.join(ziel_ordner, att_out_name)
        try:
            shutil.copyfile(att_path, att_out_path)
        except Exception as e:
            failed_log.write(f"{message_folder}\tAnhang-Fehler ({orig_name}): {e}\n")

    return True


def main():
    parser = argparse.ArgumentParser(description="pffexport-Ausgabe nach Nextcloud-Markdown konvertieren")
    parser.add_argument("--input", required=True, help="pffexport .export-Wurzelordner (enthält Message-Unterordner)")
    parser.add_argument("--output", required=True, help="Zielordner im Nextcloud-Datenverzeichnis")
    parser.add_argument("--source", choices=["privat", "kgag", "unklar"], default="unklar")
    parser.add_argument("--richtung", choices=["posteingang", "gesendet", "unklar"], default="unklar")
    parser.add_argument("--granularitaet", choices=["jahr", "monat"], default="jahr")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    failed_log_path = os.path.join(args.output, "failed_log.txt")

    total = 0
    ok = 0

    with open(failed_log_path, "a", encoding="utf-8") as failed_log:
        for root, dirs, files in os.walk(args.input):
            if "InternetHeaders.txt" in files or "OutlookHeaders.txt" in files:
                total += 1
                if process_message_folder(root, args.output, args.source, args.richtung, failed_log, args.granularitaet):
                    ok += 1
                if total % 500 == 0:
                    print(f"... {total} verarbeitet ({ok} erfolgreich)")

    print(f"\nFertig: {ok} von {total} Nachrichten erfolgreich verarbeitet.")
    print(f"Fehlgeschlagene Einträge (falls vorhanden) in: {failed_log_path}")


if __name__ == "__main__":
    sys.exit(main())
