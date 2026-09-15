#!/usr/bin/env python3
"""
telegram_bot.py

Telegram-Oberfläche für die Wissensbasis. Nimmt Fragen als Chat-Nachricht
entgegen, sucht in pgvector und antwortet mit der Claude-Antwort samt
Quellenangaben.

Sicherheit: Der Bot antwortet ausschliesslich den in TELEGRAM_ALLOWED_CHAT_ID
hinterlegten Chat-IDs (kommagetrennt). Alle anderen Anfragen werden ignoriert
und protokolliert -- ein Telegram-Bot ist grundsätzlich für jeden auffindbar,
der den Namen kennt.

Aufruf (Zugangsdaten aus Umgebungsvariablen, siehe .dahub-env):
    python3 telegram_bot.py

Läuft als Dauerprozess (Long Polling). Gedacht für systemd mit Restart=always.
"""

import html
import os
import sys
import time

import requests

try:
    import psycopg2
except ImportError:
    print("FEHLER: psycopg2 fehlt. Installiere mit:")
    print("  pip install psycopg2-binary --break-system-packages")
    sys.exit(1)

# Suchlogik aus frage.py wiederverwenden statt duplizieren
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from frage import embed_query, search, ask_claude
except ImportError:
    print("FEHLER: frage.py muss im selben Verzeichnis liegen.")
    sys.exit(1)


TELEGRAM_MAX_LEN = 4000  # Telegram-Limit ist 4096, etwas Puffer für Formatierung


def config(name, default=None, required=False):
    wert = os.environ.get(name, default)
    if required and not wert:
        print(f"FEHLER: Umgebungsvariable {name} fehlt.")
        sys.exit(1)
    return wert


class TelegramBot:
    def __init__(self, token, allowed_chat_ids, offset_datei):
        self.api = f"https://api.telegram.org/bot{token}"
        self.allowed = allowed_chat_ids
        self.offset_datei = offset_datei
        self.offset = self._offset_laden()

    def _offset_laden(self):
        """Ohne persistenten Offset würde Telegram nach einem Neustart bereits
        beantwortete Nachrichten erneut liefern -- der Bot würde sie ein
        zweites Mal bearbeiten (und ein zweites Mal Claude-Kosten auslösen)."""
        try:
            with open(self.offset_datei) as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None

    def _offset_speichern(self):
        try:
            tmp = f"{self.offset_datei}.tmp"
            with open(tmp, "w") as f:
                f.write(str(self.offset))
            os.replace(tmp, self.offset_datei)  # atomar, kein halb geschriebener Stand
        except Exception as e:
            print(f"Warnung: Offset konnte nicht gespeichert werden: {e}", flush=True)

    def _call(self, methode, **params):
        resp = requests.post(f"{self.api}/{methode}", json=params, timeout=90)
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram-Fehler ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram meldet Fehler: {str(data)[:200]}")
        return data.get("result")

    def get_updates(self, timeout=30):
        params = {"timeout": timeout}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self._call("getUpdates", **params)
        if updates:
            self.offset = updates[-1]["update_id"] + 1
            self._offset_speichern()
        return updates

    def send(self, chat_id, text, parse_mode="HTML"):
        """Teilt lange Nachrichten an Zeilengrenzen statt blind an Zeichen N --
        sonst könnte mitten in einem <code>-Tag oder einem HTML-Entity wie
        &amp; getrennt werden, was Telegram als ungültiges HTML ablehnt."""
        for teil in self._split_safe(text):
            self._call("sendMessage", chat_id=chat_id, text=teil,
                       parse_mode=parse_mode, disable_web_page_preview=True)

    @staticmethod
    def _split_safe(text, limit=TELEGRAM_MAX_LEN):
        """Zerlegt an Zeilen-, notfalls an Wortgrenzen. Offene HTML-Tags werden
        am Ende eines Teils geschlossen und im nächsten wieder geöffnet."""
        if len(text) <= limit:
            return [text]

        teile = []
        rest = text
        while rest:
            if len(rest) <= limit:
                teile.append(rest)
                break

            schnitt = rest.rfind("\n", 0, limit)
            if schnitt < limit // 2:
                schnitt = rest.rfind(" ", 0, limit)
            if schnitt < limit // 2:
                schnitt = limit  # Notfall: harte Grenze, aber nie mitten im Entity
                # Ein angeschnittenes &...; zurücknehmen
                amp = rest.rfind("&", max(0, schnitt - 10), schnitt)
                if amp != -1 and ";" not in rest[amp:schnitt]:
                    schnitt = amp

            teil, rest = rest[:schnitt], rest[schnitt:].lstrip("\n")

            # Offene Tags dieses Teils schliessen, im nächsten wieder öffnen
            for tag in ("code", "b", "i", "pre"):
                offen = teil.count(f"<{tag}>") - teil.count(f"</{tag}>")
                if offen > 0:
                    teil += f"</{tag}>" * offen
                    rest = f"<{tag}>" * offen + rest
            teile.append(teil)

        return teile

    def typing(self, chat_id):
        try:
            self._call("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:
            pass  # rein kosmetisch, darf nie den Ablauf stören


def beantworte(frage, pg_conn, cfg):
    """Sucht in der Wissensbasis und formatiert die Antwort für Telegram."""
    emb = embed_query(cfg["ollama_url"], frage)
    hits = search(pg_conn, frage, emb, top_k=5)

    if not hits:
        return "Dazu habe ich nichts in der Wissensbasis gefunden."

    antwort = ask_claude(cfg["gateway_url"], cfg["gateway_key"], frage, hits, cfg["model"])

    quellen = "\n".join(
        f"[{i}] {html.escape(h['origin_path'].split('Wissensbasis/', 1)[-1])}"
        for i, h in enumerate(hits, 1)
    )
    return f"{html.escape(antwort)}\n\n<b>Quellen:</b>\n<code>{quellen}</code>"


def main():
    cfg = {
        "token": config("TELEGRAM_TOKEN", required=True),
        "ollama_url": config("OLLAMA_URL", "http://100.93.33.0:11434"),
        "gateway_url": config("GATEWAY_URL", "http://100.93.33.0:4000"),
        "gateway_key": config("GATEWAY_KEY", required=True),
        "model": config("TELEGRAM_MODEL", "claude-sonnet"),
    }

    allowed_raw = config("TELEGRAM_ALLOWED_CHAT_ID", required=True)
    allowed = {int(x.strip()) for x in allowed_raw.split(",") if x.strip()}

    # Optional: zusätzlich einschränken, WER schreiben darf (relevant bei
    # Gruppen-Chats). Leer = jede Person im erlaubten Chat darf fragen.
    users_raw = config("TELEGRAM_ALLOWED_USER_ID", "")
    allowed_users = {int(x.strip()) for x in users_raw.split(",") if x.strip()}

    offset_datei = config("TELEGRAM_OFFSET_FILE", "/home/david/.dahub-telegram-offset")

    pg_params = {
        "host": config("PG_HOST", "100.93.33.0"),
        "port": config("PG_PORT", "5432"),
        "dbname": config("PG_DB", "knowledge"),
        "user": config("PG_USER", "dahub"),
        "password": config("PG_PASSWORD", required=True),
    }

    bot = TelegramBot(cfg["token"], allowed, offset_datei)
    print(f"Bot gestartet. {len(allowed)} erlaubte(r) Chat(s)"
          + (f", {len(allowed_users)} erlaubte(r) Nutzer" if allowed_users else "")
          + (f", fortgesetzt ab Update {bot.offset}" if bot.offset else ""), flush=True)

    while True:
        try:
            updates = bot.get_updates()
        except Exception as e:
            print(f"Fehler beim Abrufen: {e}", flush=True)
            time.sleep(10)
            continue

        for update in updates or []:
            nachricht = update.get("message") or update.get("edited_message")
            if not nachricht:
                continue

            chat = nachricht.get("chat", {})
            chat_id = chat.get("id")
            chat_typ = chat.get("type", "private")
            absender_id = (nachricht.get("from") or {}).get("id")
            text = (nachricht.get("text") or "").strip()

            # Zwei Prüfungen: Chat UND Absender. Bei einer Gruppe würde die
            # Chat-ID allein bedeuten, dass jedes Gruppenmitglied die komplette
            # Wissensbasis abfragen kann -- deshalb zusätzlich die Nutzer-ID.
            chat_ok = chat_id in allowed
            absender_ok = (not allowed_users) or (absender_id in allowed_users)

            if not chat_ok or not absender_ok:
                # Bewusst ohne Nachrichtentext: der könnte Vertrauliches enthalten
                print(f"Abgelehnt: chat={chat_id} ({chat_typ}), user={absender_id}, "
                      f"{len(text)} Zeichen", flush=True)
                continue

            if not text:
                continue

            if text.startswith("/start") or text.startswith("/help"):
                bot.send(chat_id,
                         "Stell mir einfach eine Frage zu deinen Dokumenten.\n\n"
                         "Ich durchsuche die Wissensbasis und antworte mit "
                         "Quellenangabe.\n\n"
                         "Befehle:\n"
                         "/status - Anzahl indexierter Dokumente")
                continue

            if text.startswith("/status"):
                conn = None
                try:
                    conn = psycopg2.connect(**pg_params)
                    with conn.cursor() as cur:
                        cur.execute("SELECT count(*) FROM documents")
                        docs = cur.fetchone()[0]
                        cur.execute("SELECT count(*) FROM chunks")
                        chunks = cur.fetchone()[0]
                        cur.execute("SELECT count(*) FROM file_jobs WHERE status = 'pending'")
                        offen = cur.fetchone()[0]
                    bot.send(chat_id,
                             f"<b>Wissensbasis</b>\n"
                             f"Dokumente: {docs}\n"
                             f"Textabschnitte: {chunks}\n"
                             f"Offene Jobs: {offen}")
                except Exception as e:
                    bot.send(chat_id, f"Status nicht abrufbar: {html.escape(str(e)[:200])}")
                finally:
                    if conn:
                        conn.close()  # sonst schleichendes Verbindungsleck im Dauerbetrieb
                continue

            # Bewusst nur Metadaten loggen, nicht den Fragetext -- der kann
            # Vertrauliches enthalten und landet sonst dauerhaft im Journal
            print(f"Frage von {chat_id}: {len(text)} Zeichen", flush=True)
            bot.typing(chat_id)

            conn = None
            try:
                conn = psycopg2.connect(**pg_params)
                antwort = beantworte(text, conn, cfg)
                bot.send(chat_id, antwort)
            except Exception as e:
                # Kein voller Traceback ins Journal -- der könnte Chunk-Inhalte
                # aus vertraulichen Dokumenten enthalten
                print(f"Fehler bei Anfrage von {chat_id}: {type(e).__name__}: "
                      f"{str(e)[:200]}", flush=True)
                try:
                    bot.send(chat_id, f"Da ging etwas schief: {html.escape(str(e)[:300])}")
                except Exception:
                    pass
            finally:
                if conn:
                    conn.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nBeendet.")
        sys.exit(0)
