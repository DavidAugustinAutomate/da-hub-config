#!/usr/bin/env python3
"""Sucht fuer ein gepinntes Image die neueste Version innerhalb einer Linie.

Aufruf:
  neue-version.py <image> <aktueller-tag> <linie-regex> <karenz-tage> <lokale-digests>

  image           z.B. nextcloud, gotenberg/gotenberg, ghcr.io/docling-project/docling-serve
  linie-regex     erlaubte Tags, z.B. '^33\\.\\d+\\.\\d+$' (nur diese Tags kommen in Frage)
  karenz-tage     Mindestalter eines Tags, bevor er vorgeschlagen wird
  lokale-digests  Kommagetrennt: Image-ID und RepoDigests des laufenden Images
                  (fuer die Erkennung, dass derselbe Tag neu gebaut wurde)

Ausgabe: eine JSON-Zeile
  {"aktuell": ..., "neu": <tag|null>, "art": "version|neubau|keine", "alter_tage": ...,
   "zu_jung": [[tag, alter_tage], ...], "fehler": <text|null>}

Docker Hub: Hub-API (Datum + Digest pro Tag, zaehlt nicht als Pull).
Andere Registries (ghcr.io): Registry-API v2 mit anonymem Token; Datum aus der Image-Konfiguration.
"""
import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request

TIMEOUT = 20
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


# ---------------------------------------------------------------- HTTP (austauschbar fuer Tests)
def http(url, headers=None, methode="GET"):
    """Gibt (status, header-dict, body-bytes) zurueck."""
    req = urllib.request.Request(url, headers=headers or {}, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def http_json(url, headers=None):
    status, _, body = http(url, headers)
    if status != 200:
        raise RuntimeError(f"HTTP {status} fuer {url}")
    return json.loads(body)


# ---------------------------------------------------------------- Hilfen
def zerlege(image):
    """-> (registry, repo). Docker Hub: registry 'docker.io', repo mit 'library/' fuer offizielle Images."""
    teile = image.split("/")
    if len(teile) > 1 and ("." in teile[0] or ":" in teile[0]):
        return teile[0], "/".join(teile[1:])
    repo = image if "/" in image else f"library/{image}"
    return "docker.io", repo


def schluessel(tag):
    return tuple(int(z) for z in re.findall(r"\d+", tag))


def filter_praefix(linie):
    """Literaler Anfang der Regex als Namensfilter fuer die Hub-API ('^33\\.' -> '33.')."""
    m = re.match(r"\^((?:\\\.|[A-Za-z0-9_-])*)", linie)
    return (m.group(1).replace("\\.", ".") if m else "")


def alter_tage(zeit, jetzt):
    if not zeit:
        return None
    t = dt.datetime.fromisoformat(zeit.replace("Z", "+00:00"))
    return (jetzt - t).total_seconds() / 86400


# ---------------------------------------------------------------- Docker Hub
def hub_tags(repo, praefix):
    """-> {tag: (digest, zeitpunkt)}"""
    ergebnis = {}
    url = (f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100"
           + (f"&name={urllib.parse.quote(praefix)}" if praefix else ""))
    seiten = 0
    while url and seiten < 50:
        d = http_json(url)
        for t in d.get("results", []):
            ergebnis[t["name"]] = (t.get("digest"), t.get("tag_last_pushed") or t.get("last_updated"))
        url = d.get("next")
        seiten += 1
    return ergebnis


# ---------------------------------------------------------------- Registry v2 (ghcr.io u.a.)
def token(registry, repo):
    status, h, _ = http(f"https://{registry}/v2/")
    auth = h.get("www-authenticate", "")
    if status == 200 or not auth.lower().startswith("bearer"):
        return None
    felder = dict(re.findall(r'(\w+)="([^"]*)"', auth))
    q = {"scope": f"repository:{repo}:pull"}
    if "service" in felder:
        q["service"] = felder["service"]
    d = http_json(felder["realm"] + "?" + urllib.parse.urlencode(q))
    return d.get("token") or d.get("access_token")


def v2_tags(registry, repo, tok):
    kopf = {"Authorization": f"Bearer {tok}"} if tok else {}
    tags, url, seiten = [], f"https://{registry}/v2/{repo}/tags/list?n=1000", 0
    while url and seiten < 50:
        status, h, body = http(url, kopf)
        if status != 200:
            raise RuntimeError(f"HTTP {status} fuer Tag-Liste")
        tags += json.loads(body).get("tags") or []
        m = re.search(r'<([^>]+)>;\s*rel="next"', h.get("link", ""))
        url = urllib.parse.urljoin(f"https://{registry}", m.group(1)) if m else None
        seiten += 1
    return tags


def v2_info(registry, repo, tag, tok):
    """-> (index-digest, zeitpunkt der Image-Konfiguration fuer linux/amd64)"""
    kopf = {"Accept": ACCEPT}
    if tok:
        kopf["Authorization"] = f"Bearer {tok}"
    status, h, body = http(f"https://{registry}/v2/{repo}/manifests/{tag}", kopf)
    if status != 200:
        raise RuntimeError(f"HTTP {status} fuer Manifest {tag}")
    digest = h.get("docker-content-digest")
    m = json.loads(body)
    if "manifests" in m:
        passend = [x for x in m["manifests"]
                   if x.get("platform", {}).get("os") == "linux" and x.get("platform", {}).get("architecture") == "amd64"]
        if not passend:
            return digest, None
        status, _, body = http(f"https://{registry}/v2/{repo}/manifests/{passend[0]['digest']}", kopf)
        m = json.loads(body)
    cfg = m.get("config", {}).get("digest")
    if not cfg:
        return digest, None
    blob_kopf = {"Authorization": kopf["Authorization"]} if tok else {}
    status, _, body = http(f"https://{registry}/v2/{repo}/blobs/{cfg}", blob_kopf)
    return digest, json.loads(body).get("created") if status == 200 else None


# ---------------------------------------------------------------- Kern
def suche(image, aktuell, linie, karenz, lokal, jetzt=None):
    jetzt = jetzt or dt.datetime.now(dt.timezone.utc)
    regex = re.compile(linie)
    registry, repo = zerlege(image)
    aus = {"aktuell": aktuell, "neu": None, "art": "keine", "alter_tage": None, "zu_jung": [], "fehler": None}

    if registry == "docker.io":
        info = hub_tags(repo, filter_praefix(linie))
        tags = list(info)
        holen = lambda t: info.get(t, (None, None))
    else:
        tok = token(registry, repo)
        tags = v2_tags(registry, repo, tok)
        holen = lambda t: v2_info(registry, repo, t, tok)

    kandidaten = sorted((t for t in tags if regex.search(t) and schluessel(t) > schluessel(aktuell)),
                        key=schluessel, reverse=True)
    for t in kandidaten:
        _, zeit = holen(t)
        alter = alter_tage(zeit, jetzt)
        if alter is None or alter < karenz:
            aus["zu_jung"].append([t, None if alter is None else round(alter, 1)])
            continue
        aus.update(neu=t, art="version", alter_tage=round(alter, 1))
        return aus

    # keine neuere Version: wurde derselbe Tag neu gebaut?
    if aktuell in tags or registry == "docker.io":
        digest, zeit = holen(aktuell)
        if digest and digest not in lokal:
            alter = alter_tage(zeit, jetzt)
            if alter is not None and alter >= karenz:
                aus.update(neu=aktuell, art="neubau", alter_tage=round(alter, 1))
            else:
                aus["zu_jung"].append([aktuell + " (Neubau)", None if alter is None else round(alter, 1)])
    return aus


def main():
    if len(sys.argv) != 6:
        print(__doc__)
        return 2
    image, aktuell, linie, karenz, lokal = sys.argv[1:]
    lokal = {x.split("@")[-1] for x in lokal.split(",") if x}
    try:
        aus = suche(image, aktuell, linie, float(karenz), lokal)
    except Exception as e:  # Netz/Registry: als Fehler melden, nie abstuerzen
        aus = {"aktuell": aktuell, "neu": None, "art": "keine", "alter_tage": None, "zu_jung": [],
               "fehler": f"{type(e).__name__}: {e}"}
    print(json.dumps(aus, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
