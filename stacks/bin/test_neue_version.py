"""Mocktests fuer neue-version.py (ohne Netz)."""
import datetime as dt
import importlib.util
import json
import os
import sys

spec = importlib.util.spec_from_file_location("nv", os.path.join(os.path.dirname(__file__), "neue-version.py"))
nv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nv)

JETZT = dt.datetime(2026, 10, 4, 3, 30, tzinfo=dt.timezone.utc)
def vor(tage):
    return (JETZT - dt.timedelta(days=tage)).isoformat().replace("+00:00", "Z")

fehler = 0
def pruefe(name, ist, soll):
    global fehler
    ok = all(ist.get(k) == v for k, v in soll.items())
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f"\n     ist={ist}\n     soll={soll}"))
    fehler += not ok

# --- Docker Hub: Hub-API simulieren
def hub_mock(tags):
    def http(url, headers=None, methode="GET"):
        assert url.startswith("https://hub.docker.com/v2/repositories/"), url
        res = [{"name": n, "digest": d, "tag_last_pushed": z} for n, (d, z) in tags.items()]
        return 200, {}, json.dumps({"results": res, "next": None}).encode()
    return http

nv.http = hub_mock({
    "33.0.8": ("sha256:alt", vor(20)), "33.0.9": ("sha256:n9", vor(10)), "33.0.10": ("sha256:n10", vor(2)),
    "34.0.0": ("sha256:m", vor(30)), "33.0.11-rc1": ("sha256:rc", vor(30)), "33.0.9-apache": ("sha256:a", vor(10)),
})
LINIE = r"^33\.\d+\.\d+$"
pruefe("nextcloud: 33.0.10 zu jung, 33.0.9 gewaehlt, 34 und rc ignoriert",
       nv.suche("nextcloud", "33.0.8", LINIE, 7, {"sha256:alt"}, JETZT),
       {"neu": "33.0.9", "art": "version", "zu_jung": [["33.0.10", 2.0]]})
pruefe("numerische Sortierung (33.0.10 > 33.0.9) bei Karenz 0",
       nv.suche("nextcloud", "33.0.8", LINIE, 0, {"sha256:alt"}, JETZT), {"neu": "33.0.10"})
pruefe("schon aktuell, gleicher Digest -> keine",
       nv.suche("nextcloud", "33.0.10", LINIE, 7, {"sha256:n10"}, JETZT), {"neu": None, "art": "keine"})

nv.http = hub_mock({"3.19": ("sha256:neu", vor(21)), "3.20": ("sha256:x", vor(1))})
pruefe("libreoffice: Linie ^3\\.19$, Tag neu gebaut, alt genug -> neubau",
       nv.suche("libreofficedocker/libreoffice-unoserver", "3.19", r"^3\.19$", 7, {"sha256:alt"}, JETZT),
       {"neu": "3.19", "art": "neubau"})
nv.http = hub_mock({"3.19": ("sha256:neu", vor(2))})
pruefe("libreoffice: Neubau zu jung -> keine, aber gemeldet",
       nv.suche("libreofficedocker/libreoffice-unoserver", "3.19", r"^3\.19$", 7, {"sha256:alt"}, JETZT),
       {"neu": None, "zu_jung": [["3.19 (Neubau)", 2.0]]})
nv.http = hub_mock({"11.4.13": ("sha256:lokal", vor(40)), "11.4.14": ("sha256:b", vor(8)), "11.8.1": ("sha256:c", vor(90))})
pruefe("mariadb: 11.4.14 in Linie, 11.8 ausserhalb",
       nv.suche("mariadb", "11.4.13", r"^11\.4\.\d+$", 7, {"sha256:lokal"}, JETZT), {"neu": "11.4.14"})

# --- ghcr.io: Registry v2 simulieren
def ghcr_mock(tags):  # tags: {name: (index_digest, created)}
    def http(url, headers=None, methode="GET"):
        if url == "https://ghcr.io/v2/":
            return 401, {"www-authenticate": 'Bearer realm="https://ghcr.io/token",service="ghcr.io"'}, b""
        if url.startswith("https://ghcr.io/token"):
            assert "scope=repository%3Adocling-project%2Fdocling-serve%3Apull" in url, url
            return 200, {}, b'{"token":"t"}'
        assert headers and headers.get("Authorization") == "Bearer t", url
        if "/tags/list" in url:
            return 200, {}, json.dumps({"tags": list(tags) + ["latest"]}).encode()
        if "/manifests/sha256:plat-" in url:
            name = url.rsplit("sha256:plat-", 1)[1]
            return 200, {}, json.dumps({"config": {"digest": "sha256:cfg-" + name}}).encode()
        if "/manifests/" in url:
            name = url.rsplit("/", 1)[1]
            return 200, {"docker-content-digest": tags[name][0]}, json.dumps({"manifests": [
                {"digest": "sha256:plat-" + name, "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:arm", "platform": {"os": "linux", "architecture": "arm64"}}]}).encode()
        if "/blobs/sha256:cfg-" in url:
            name = url.rsplit("sha256:cfg-", 1)[1]
            return 200, {}, json.dumps({"created": tags[name][1]}).encode()
        raise AssertionError(url)
    return http

nv.http = ghcr_mock({"v1.32.0": ("sha256:lok", vor(30)), "v1.33.0": ("sha256:a", vor(9)), "v1.33.1": ("sha256:b", vor(3)), "v2.0.0": ("sha256:c", vor(20))})
pruefe("docling (ghcr): v1.33.1 zu jung, v1.33.0 gewaehlt, v2 ausserhalb",
       nv.suche("ghcr.io/docling-project/docling-serve", "v1.32.0", r"^v1\.\d+\.\d+$", 7, {"sha256:lok"}, JETZT),
       {"neu": "v1.33.0", "art": "version", "zu_jung": [["v1.33.1", 3.0]]})

pruefe("zerlege: offizielles Image", dict(zip(("r", "p"), nv.zerlege("mariadb"))), {"r": "docker.io", "p": "library/mariadb"})
pruefe("zerlege: ghcr", dict(zip(("r", "p"), nv.zerlege("ghcr.io/a/b"))), {"r": "ghcr.io", "p": "a/b"})
pruefe("filter_praefix", {"x": nv.filter_praefix(r"^v2\.\d+\.\d+$")}, {"x": "v2."})

print("FEHLER:", fehler)
sys.exit(1 if fehler else 0)
