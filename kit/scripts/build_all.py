"""Build every site of this repository and check the output. The ONLY supported way to build.

Run from a content repository:

    python ../company-resources/kit/scripts/build_all.py              # all sites of this repo
    python ../company-resources/kit/scripts/build_all.py management   # one

Output: build/<site>/site/ (deployed to Cloudflare Pages project <project_prefix><site>).
Uses the `zensical` on PATH, or the ZENSICAL env var.

Checks after each build (fails if any is false):
  1. no Markdown source is published;
  2. every staged page belongs to this site (kit/portals.yml) or was generated,
     so a page from another site (another audience) can never end up here;
  3. the search index exists and is not empty;
  4. _headers (security headers) is present.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_site import stage  # noqa: E402
from portal import (load_config, read_doc, repo_name, repo_root, repo_sites,  # noqa: E402
                    site_for, site_prefix)


def check_site(cfg, site_id, out, root):
    errors = []
    site, staged = out / "site", out / "docs"
    if not site.is_dir():
        return [f"{site_id}: build produced no site/ folder"]
    md = [p.relative_to(site).as_posix() for p in site.rglob("*.md")]
    if md:
        errors.append(f"{site_id}: Markdown source published: {md[:5]}")
    sites = repo_sites(cfg, cfg["sites"][site_id]["repo"])
    prefix = site_prefix(sites[site_id])
    for page in staged.rglob("*.md"):
        rel = page.relative_to(staged).as_posix()
        source = f"{prefix}/{rel}" if prefix else rel
        meta, _ = read_doc(page)
        if (meta or {}).get("generated"):
            continue
        if not (root / "docs" / source).exists() or site_for(source, sites) != site_id:
            errors.append(f"{site_id}: page {rel} does not belong to this site")
    index = site / "search.json"
    if not index.exists() or not json.loads(index.read_text(encoding="utf-8")).get("items"):
        errors.append(f"{site_id}: search index missing or empty")
    if not (site / "_headers").exists():
        errors.append(f"{site_id}: _headers missing")
    return errors


def main(argv):
    cfg = load_config()
    root = repo_root()
    zensical = os.environ.get("ZENSICAL", "zensical")
    failed = []
    for site_id in argv or list(repo_sites(cfg, repo_name(root))):
        out = stage(cfg, site_id, root)
        result = subprocess.run([zensical, "build", "--clean", "--strict"], cwd=out,
                                capture_output=True, text=True)
        print(result.stdout + result.stderr, end="")
        if result.returncode != 0:
            failed.append(f"{site_id}: zensical build failed")
            continue
        errors = check_site(cfg, site_id, out, root)
        failed += errors
        if not errors:
            print(f"OK {site_id}: build/{site_id}/site ({sum(1 for _ in (out / 'site').rglob('*.html'))} pages)")
    for f in failed:
        print(f"::error::{f}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
