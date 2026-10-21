"""Check from the outside (signed out) that every site is protected by Cloudflare Access.

    python .../kit/scripts/smoke.py                  # after deploy: this repo's sites must be protected
    python .../kit/scripts/smoke.py --all            # every site (front door's scheduled monitor)
    python .../kit/scripts/smoke.py --before-deploy  # guard: refuse to deploy if a site is PUBLIC

For each site of this repository (--all: every site) it requests, without login:
  - https://<site>/ and https://<site>/search.json      -> must redirect to *.cloudflareaccess.com
  - https://smoke-<random>.<site>/ (a preview address)  -> must redirect to *.cloudflareaccess.com
and the front door's public pages (/ and /no-access/)   -> must answer 200.

A 200 from a protected address means documents are PUBLIC: that is reported as
a security failure, not a pass. With --before-deploy, a 404 or an unknown
hostname is accepted (the site has never been deployed); everything else must
already be protected.
Only plain anonymous GETs are sent; nothing is logged in to or changed.
"""
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portal import hostname, load_config, repo_name, repo_sites  # noqa: E402


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(url):
    """(status, Location header) without following redirects."""
    try:
        with OPENER.open(urllib.request.Request(url, headers={"User-Agent": "nerdience-smoke"}), timeout=20) as r:
            return r.status, r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, str(e)


def verdict(status, location, before_deploy=False):
    """'ok' | 'PUBLIC' | 'error: ...' for a URL that must be protected."""
    host = urlparse(location).hostname or ""
    if status in (301, 302, 303, 307, 308) and host.endswith(".cloudflareaccess.com"):
        return "ok"
    if status == 200:
        return "PUBLIC"
    unknown_host = status == 0 and ("getaddrinfo" in location or "Name or service not known" in location)
    if before_deploy and (status == 404 or unknown_host):
        return "ok"                              # never deployed yet: nothing is public
    return f"error: HTTP {status} {location[:80]}"


def main(argv):
    before = "--before-deploy" in argv
    cfg = load_config()
    checks = []
    sites = cfg["sites"] if "--all" in argv else repo_sites(cfg, repo_name())
    for site_id in sites:
        host = hostname(cfg, site_id)
        checks += [f"https://{host}/", f"https://{host}/search.json",
                   f"https://smoke-{secrets.token_hex(4)}.{host}/"]
    failures = []
    for url in checks:
        status, location = fetch(url)
        v = verdict(status, location, before)
        print(f"{v:8} {status} {url}")
        if v != "ok":
            failures.append(f"{url}: {'PUBLIC WITHOUT LOGIN' if v == 'PUBLIC' else v}")
    if not before:
        door = cfg["front_door"].rstrip("/")
        for url in (f"{door}/", f"{door}/no-access/"):
            status, _ = fetch(url)
            print(f"{'ok' if status == 200 else 'error':8} {status} {url}")
            if status != 200:
                failures.append(f"{url}: front door page answered {status}")
    for f in failures:
        print(f"::error::{f}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
