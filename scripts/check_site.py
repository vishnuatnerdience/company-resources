"""Checks for the front-door site (run in CI before deploying).

The site is plain HTML in public/, so there is no build step. This script
catches the mistakes that matter for it:

  1. every HTML page tells search engines not to index it (the landing and
     no-access pages are public on the internet);
  2. every local link, image, stylesheet and script points to a file that
     exists in public/;
  3. no page loads scripts from other websites (only Google Fonts CSS is
     allowed from outside);
  4. no page uses plain http:// links;
  5. the public pages contain no links into the portals (hosts read from
     kit/portals.yml), so the public site reveals nothing about internal structure;
  6. the template downloads exist.

Usage: python scripts/check_site.py
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

PUBLIC = Path("public")
PUBLIC_PAGES = {"index.html", "no-access/index.html"}   # not behind Access
ALLOWED_EXTERNAL_CSS = ("https://fonts.googleapis.com/",)


def portal_hosts():
    """Every portal hostname in kit/portals.yml (public pages must not link to them)."""
    import yaml
    cfg = yaml.safe_load(Path("kit/portals.yml").read_text(encoding="utf-8"))
    return tuple(f"{cfg['project_prefix']}{sid}.{cfg['host_suffix']}" for sid in cfg["sites"])


PORTAL_HOSTS = portal_hosts()


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.scripts, self.robots = [], [], False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("name") == "robots" and "noindex" in (a.get("content") or ""):
            self.robots = True
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append((tag, a[key]))


def main():
    errors = []
    pages = sorted(PUBLIC.rglob("*.html"))
    if not pages:
        sys.exit("No HTML pages found in public/.")
    for page in pages:
        rel = page.relative_to(PUBLIC).as_posix()
        parser = Refs()
        parser.feed(page.read_text(encoding="utf-8"))

        if not parser.robots:
            errors.append(f"{rel}: missing <meta name=\"robots\" content=\"noindex, nofollow\">")
        for src in parser.scripts:
            if urlparse(src).scheme:
                errors.append(f"{rel}: loads a script from another site: {src}")
        for tag, ref in parser.refs:
            url = urlparse(ref)
            if url.scheme == "http":
                errors.append(f"{rel}: insecure http:// link: {ref}")
            if url.scheme in ("https",):
                if tag == "link" and "stylesheet" in ref and not ref.startswith(ALLOWED_EXTERNAL_CSS):
                    errors.append(f"{rel}: external stylesheet not allowed: {ref}")
                if rel in PUBLIC_PAGES and url.hostname in PORTAL_HOSTS:
                    errors.append(f"{rel}: public page links into a portal: {ref}")
                continue
            if url.scheme or ref.startswith(("#", "mailto:")) or ref.startswith("/cdn-cgi/"):
                continue                      # Cloudflare Access endpoints exist only when deployed
            target = (PUBLIC / ref.lstrip("/")) if ref.startswith("/") else (page.parent / url.path)
            target = target.resolve()
            if target.is_dir() or url.path.endswith("/"):
                target = target / "index.html"
            if not target.exists():
                errors.append(f"{rel}: broken local reference: {ref}")

    for required in ("robots.txt", "_headers", "downloads/template.md", "downloads/example.md"):
        if not (PUBLIC / required).exists():
            errors.append(f"public/{required} is missing")

    if errors:
        print("Site check failed:")
        for e in errors:
            print(f"- {e}")
        sys.exit(1)
    print(f"Site check passed ({len(pages)} pages).")


if __name__ == "__main__":
    main()
