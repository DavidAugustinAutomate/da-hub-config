#!/usr/bin/env python3
"""Versions-Check fuer gepinnte Container auf da-hub.

Watchtower meldet nur bei beweglichen Tags. Gepinnte Dienste (n8n, LiteLLM)
fallen dort durch. Dieses Skript vergleicht die installierte Version gegen den
neuesten GitHub-Release und meldet ueber notify.sh.

Meldet nur, wenn sich die verfuegbare Version seit der letzten Meldung
geaendert hat -- kein Woche-fuer-Woche-Wiederholen derselben Zeile.

Aufruf:
  python3 ~/scripts/check-versionen.py            # normaler Lauf
  python3 ~/scripts/check-versionen.py --dry-run  # nur ausgeben, nicht melden
  python3 ~/scripts/check-versionen.py --force    # melden, auch wenn bekannt
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

# name, container, GitHub-Repo
DIENSTE = [
    ("n8n", "n8n", "n8n-io/n8n"),
    ("LiteLLM", "litellm", "BerriAI/litellm"),
]

NOTIFY = os.path.expanduser("~/scripts/notify.sh")
ZUSTAND = os.path.expanduser("~/.local/state/dahub-versionen.json")
TIMEOUT = 20


def installierte_version(container):
    """Liest den Image-Tag des laufenden Containers."""
    try:
        aus = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", container],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None, "Container nicht gefunden"
    except (subprocess.TimeoutExpired, FileNotFoundError) as fehler:
        return None, f"docker nicht erreichbar ({fehler.__class__.__name__})"

    # ghcr.io/berriai/litellm:v1.85.0 -> v1.85.0
    # Doppelpunkt in der Registry-Adresse (host:port) beruecksichtigen:
    # nur trennen, wenn nach dem Doppelpunkt kein Schraegstrich mehr folgt.
    letzter = aus.rfind(":")
    if letzter == -1 or "/" in aus[letzter:]:
        return None, f"kein Tag im Image '{aus}'"
    tag = aus[letzter + 1:]
    if tag in ("latest", "main", "stable"):
        return None, f"beweglicher Tag '{tag}' -- Watchtower meldet diesen Dienst"
    return normalisieren(tag), None


def neueste_version(repo):
    """Holt den neuesten Nicht-Vorabrelease von GitHub."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    anfrage = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "da-hub-versionscheck",
        },
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT) as antwort:
            daten = json.load(antwort)
    except urllib.error.HTTPError as fehler:
        if fehler.code == 403:
            return None, "GitHub-Limit erreicht (60 Anfragen/Stunde)"
        return None, f"GitHub HTTP {fehler.code}"
    except Exception as fehler:  # Netz, DNS, JSON
        return None, f"GitHub nicht erreichbar ({fehler.__class__.__name__})"

    tag = daten.get("tag_name")
    if not tag:
        return None, "kein tag_name in der Antwort"
    return normalisieren(tag), None


def normalisieren(tag):
    """'n8n@2.38.7' -> '2.38.7', 'v1.101.0' -> '1.101.0'."""
    tag = tag.strip()
    if "@" in tag:
        tag = tag.rsplit("@", 1)[1]
    return tag.lstrip("vV")


def als_zahlen(version):
    """'2.38.7' -> (2, 38, 7); nicht-numerische Teile werden zu -1."""
    teile = re.split(r"[.\-+]", version)
    zahlen = []
    for teil in teile[:3]:
        zahlen.append(int(teil) if teil.isdigit() else -1)
    while len(zahlen) < 3:
        zahlen.append(0)
    return tuple(zahlen)


def zustand_lesen():
    try:
        with open(ZUSTAND, encoding="utf-8") as datei:
            return json.load(datei)
    except (OSError, ValueError):
        return {}


def zustand_schreiben(zustand):
    os.makedirs(os.path.dirname(ZUSTAND), exist_ok=True)
    tmp = ZUSTAND + ".tmp"
    with open(tmp, "w", encoding="utf-8") as datei:
        json.dump(zustand, datei, ensure_ascii=False, indent=1)
    os.replace(tmp, ZUSTAND)


def melden(titel, text, prioritaet="default"):
    if not os.path.exists(NOTIFY):
        print(f"WARNUNG: {NOTIFY} fehlt -- keine Meldung gesendet", file=sys.stderr)
        return
    subprocess.run([NOTIFY, titel, text, prioritaet], timeout=60, check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="nur ausgeben, nichts melden, Zustand nicht schreiben")
    parser.add_argument("--force", action="store_true",
                        help="melden, auch wenn die Version schon gemeldet wurde")
    argumente = parser.parse_args()

    zustand = zustand_lesen()
    zeilen = []
    probleme = []
    neuer_zustand = dict(zustand)

    for name, container, repo in DIENSTE:
        ist, fehler_ist = installierte_version(container)
        if fehler_ist:
            probleme.append(f"{name}: {fehler_ist}")
            continue

        soll, fehler_soll = neueste_version(repo)
        if fehler_soll:
            probleme.append(f"{name}: {fehler_soll}")
            continue

        if ist == soll:
            print(f"{name}: {ist} -- aktuell")
            neuer_zustand[name] = soll
            continue

        ist_z, soll_z = als_zahlen(ist), als_zahlen(soll)
        if soll_z < ist_z:
            print(f"{name}: {ist} installiert, GitHub meldet {soll} -- uebersprungen")
            continue

        sprung = " (MAJOR-Sprung)" if soll_z[0] != ist_z[0] else ""
        zeile = f"{name}: {ist} -> {soll}{sprung}"
        print(zeile)

        if zustand.get(name) == soll and not argumente.force:
            print(f"  (bereits gemeldet, keine erneute Meldung)")
            continue
        zeilen.append(zeile)
        neuer_zustand[name] = soll

    if probleme:
        for zeile in probleme:
            print(f"PROBLEM: {zeile}", file=sys.stderr)

    if argumente.dry_run:
        print("\n--dry-run: keine Meldung, Zustand unveraendert")
        return 0

    if zeilen:
        melden("da-hub: neue Versionen", "\n".join(zeilen),
               "high" if any("MAJOR" in z for z in zeilen) else "default")
    if probleme:
        melden("da-hub: Versions-Check gestoert", "\n".join(probleme), "low")

    zustand_schreiben(neuer_zustand)
    return 0


if __name__ == "__main__":
    sys.exit(main())
