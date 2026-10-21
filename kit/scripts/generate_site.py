"""Stage one portal site as a complete Zensical project, with NOTHING edited by hand.

Run from a content repository (company-engineering or company-hr-general):

    python ../company-resources/kit/scripts/generate_site.py              # every site of this repo
    python ../company-resources/kit/scripts/generate_site.py management   # one site

For each site of the repository (kit/portals.yml) it writes build/<site>/:
    docs/            ONLY the pages that belong to this site (longest folder match);
                     a single-folder site gets that folder as its root
      + index.md     created for any folder that lacks one
      + card grids   "Sections" and "Documents" appended to every index.md
      + hero         on the site home page (search box, counts)
      + recent list  "Recently updated" on the home page (git dates, else last_reviewed)
      + related      "Related documents" on every page (same folder, shared tags)
      + review_overdue: true on pages past their review date (shown as a badge)
      + _headers     security headers for Cloudflare Pages
      + assets/      shared theme assets
    overrides/       shared theme templates
    zensical.toml    [project] + nav generated from the folders, + theme/zensical.base.toml

Editors therefore only add, move or delete .md files (in any folder, new or
existing). Ordering: optional `order: <n>` in a page's (or a folder's index.md)
frontmatter; otherwise A-Z by title.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portal import (KIT, SKIP_DIRS, doc_order, doc_title, load_config, read_doc,  # noqa: E402
                    repo_name, repo_root, repo_sites, site_for, site_prefix, site_url,
                    title_from_name)

THEME = KIT / "theme"
UTILITY_PAGES = set()
GENERIC_TAGS = {"index", "overview", "template"}

HEADERS = """/*
  X-Robots-Tag: noindex, nofollow
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: DENY
  Permissions-Policy: camera=(), microphone=(), geolocation=()
"""


# ------------------------------------------------------------------ tree walk
def children(folder):
    """(subfolders, documents) of a folder, each sorted by (order, title)."""
    subs = [d for d in folder.iterdir() if d.is_dir() and d.name not in SKIP_DIRS]
    docs = [p for p in folder.glob("*.md") if p.name != "index.md" and p.name not in UTILITY_PAGES]
    subs.sort(key=lambda d: (folder_order(d), folder_title(d).lower()))
    docs.sort(key=lambda p: (doc_order(p), doc_title(p).lower()))
    return subs, docs


def folder_title(folder):
    index = folder / "index.md"
    return doc_title(index) if index.exists() else title_from_name(folder.name)


def folder_order(folder):
    index = folder / "index.md"
    return doc_order(index) if index.exists() else 999


def build_nav(dept_dir):
    """Nav for zensical.toml, as nested [ {label: path | [..]} ] relative to dept_dir."""
    def section(folder):
        rel = folder.relative_to(dept_dir).as_posix()
        subs, docs = children(folder)
        items = [f"{rel}/index.md"]
        items += [{doc_title(p): p.relative_to(dept_dir).as_posix()} for p in docs]
        items += [{folder_title(d): section(d)} for d in subs]
        return items

    subs, docs = children(dept_dir)
    nav = [{"Home": "index.md"}]
    nav += [{folder_title(d): section(d)} for d in subs]
    nav += [{doc_title(p): p.relative_to(dept_dir).as_posix()} for p in docs]
    return nav


# ------------------------------------------------------------------ cards
def description(path):
    """'## Purpose' paragraph if present, else the first plain paragraph."""
    _, body = read_doc(path)
    m = re.search(r"^## Purpose\s*\n+(.+?)\s*$", body, flags=re.M)
    if m:
        return m.group(1)
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith(("#", "-", ">", "<", "|", "_", "[", "!")):
            return s
    return ""


def page_count(folder):
    return sum(1 for p in folder.rglob("*.md") if p.name != "index.md" and p.name not in UTILITY_PAGES)


def card(title, text, href, meta, kind):
    """One card. `kind` is 'section' or 'doc' (different icon and layout on mobile)."""
    desc = f'    <span class="nd-card__desc">{html.escape(text)}</span>\n' if text else ""
    return (f'  <a class="nd-card nd-card--{kind}" href="{href}">\n'
            f'    <span class="nd-card__title">{html.escape(title)}</span>\n'
            f'{desc}'
            f'    <span class="nd-card__meta">{html.escape(meta)}</span>\n'
            f'  </a>')


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def card_grids(folder):
    subs, docs = children(folder)
    parts = []
    if subs:
        parts += ['<h2 class="nd-section-label" id="sections">Sections</h2>', "",
                  '<div class="nd-grid" markdown="0">']
        parts += [card(folder_title(d),
                       description(d / "index.md") if (d / "index.md").exists() else "",
                       f"{d.name}/", plural(page_count(d), "page"), "section") for d in subs]
        parts += ["</div>", ""]
    if docs:
        parts += ['<h2 class="nd-section-label">Documents</h2>', "", '<div class="nd-grid nd-grid--docs" markdown="0">']
        parts += [card(doc_title(p), description(p), f"{p.stem}/", reviewed_label(p), "doc") for p in docs]
        parts += ["</div>", ""]
    return "\n".join(parts)


def reviewed_label(path):
    meta, _ = read_doc(path)
    when = str((meta or {}).get("last_reviewed", "")).strip()
    return f"Reviewed {when}" if when else "Read"


def hero(dept_cfg, docs_dir):
    title = html.escape(dept_cfg["title"])
    sections = sum(1 for d in docs_dir.iterdir() if d.is_dir() and d.name not in SKIP_DIRS)
    stats = f"{plural(sections, 'section')} · {plural(page_count(docs_dir), 'page')}"
    # <label for="__search"> opens the theme's search dialog without any JavaScript.
    # UI strings are in data-label (shown via CSS) so they stay out of the search index.
    return ('<div class="nd-hero" markdown="0">\n'
            '  <p class="nd-hero__eyebrow" data-label="Nerdience Knowledge Portal"></p>\n'
            f'  <h1 class="nd-hero__title">{title}</h1>\n'
            f'  <p class="nd-hero__lead">{html.escape(dept_cfg.get("description", ""))}</p>\n'
            f'  <label class="nd-search" for="__search" role="button" tabindex="0" aria-label="Search {title}" '
            'onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();this.click()}">\n'
            f'    <span class="nd-search__text" data-label="Search {title}"></span>\n'
            '    <kbd class="nd-search__key" data-label="Ctrl K"></kbd>\n'
            '  </label>\n'
            f'  <p class="nd-hero__stats" data-label="{stats}"></p>\n'
            '</div>\n')


def recently_updated(src_dir, docs_dir, limit=6, root=None):
    """Latest pages by git commit date (or last_reviewed when not in a git checkout)."""
    root = root or repo_root()
    dates = {}
    try:
        out = subprocess.run(["git", "log", "--format=@%cs", "--name-only", "--", str(src_dir)],
                             cwd=root, capture_output=True, text=True, check=True).stdout
        day = None
        for line in out.splitlines():
            if line.startswith("@"):
                day = line[1:]
            elif line.strip():
                dates.setdefault((root / line.strip()).resolve(), day)
    except (OSError, subprocess.CalledProcessError):
        pass
    rows = []
    for page in docs_dir.rglob("*.md"):
        rel = page.relative_to(docs_dir)
        if page.name in UTILITY_PAGES or rel.parts[0] in SKIP_DIRS or page.name == "index.md":
            continue
        meta, _ = read_doc(page)
        when = dates.get((src_dir / rel).resolve()) or str((meta or {}).get("last_reviewed", ""))
        if when:
            section = folder_title(page.parent) if page.parent != docs_dir else ""
            href = rel.with_suffix("").as_posix() + "/"
            rows.append((when, doc_title(page), section, href))
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    if not rows:
        return ""
    items = "\n".join(
        f'  <li><a href="{href}"><span class="nd-recent__title">{html.escape(t)}</span>'
        f'<span class="nd-recent__where">{html.escape(s)}</span></a>'
        f'<time datetime="{w}">{w}</time></li>' for w, t, s, href in rows[:limit])
    return ('<h2 class="nd-section-label" id="recent">Recently updated</h2>\n\n'
            f'<ul class="nd-recent" markdown="0">\n{items}\n</ul>\n')


def mark_overdue(docs_dir, today=None):
    """Add `review_overdue: true` to staged pages past last_reviewed + review_cycle_days."""
    today = today or date.today()
    for page in docs_dir.rglob("*.md"):
        meta, _ = read_doc(page)
        if not meta:
            continue
        try:
            reviewed = date.fromisoformat(str(meta.get("last_reviewed")))
            cycle = int(meta.get("review_cycle_days"))
        except (TypeError, ValueError):
            continue
        if (today - reviewed).days > cycle:
            text = page.read_text(encoding="utf-8")
            page.write_text(text.replace("\n---", "\nreview_overdue: true\n---", 1), encoding="utf-8")


def generated_index(folder, dept_root):
    """Frontmatter for a folder the editor created without an index.md."""
    title = title_from_name(folder.name)
    meta, _ = read_doc(dept_root / "index.md") if (dept_root / "index.md").exists() else ({}, "")
    meta = meta or {}
    return ("---\n"
            f"title: {json.dumps(title)}\n"
            f"owner: {json.dumps(str(meta.get('owner', 'Docs team')))}\n"
            f"department: {json.dumps(str(meta.get('department', 'General')))}\n"
            f"classification: {meta.get('classification', 'internal')}\n"
            "status: draft\n"
            'version: "1.0"\n'
            f'last_reviewed: "{meta.get("last_reviewed", "2026-01-01")}"\n'
            "review_cycle_days: 365\n"
            "tags: [index]\n"
            "utility_page: true\n"
            "generated: true\n"
            "---\n\n"
            f"# {title}\n")


def finish_indexes(docs_dir, dept_cfg, recent=""):
    """Create missing index.md files, then append card grids (and hero + recent list on home)."""
    folders = [docs_dir] + sorted(d for d in docs_dir.rglob("*")
                                  if d.is_dir() and not set(d.relative_to(docs_dir).parts) & SKIP_DIRS)
    for folder in folders:
        index = folder / "index.md"
        if not index.exists():
            index.write_text(generated_index(folder, docs_dir), encoding="utf-8")
    for folder in folders:                      # second pass: every index now exists
        index = folder / "index.md"
        text = index.read_text(encoding="utf-8").rstrip() + "\n"
        if folder == docs_dir:
            meta_block = re.match(r"\A---\r?\n.*?\r?\n---\r?\n", text, re.S)
            head = meta_block.group(0) if meta_block else ""
            if "hide:" not in head:
                head = head[:-4] + "hide:\n  - toc\n---\n" if head else "---\nhide:\n  - toc\n---\n"
            text = head + "\n" + hero(dept_cfg, docs_dir)
        grids = card_grids(folder)
        if grids:
            text += "\n" + grids
        if folder == docs_dir and recent:
            text += "\n" + recent
        index.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------ toml
def toml_value(value, indent=0):
    """TOML for str / int / bool / list / dict (nav-style inline tables)."""
    pad = "  " * indent
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(k, ensure_ascii=False)} = {toml_value(v, indent)}"
                                for k, v in value.items()) + " }"
    if isinstance(value, list):
        if not value:
            return "[]"
        inner = ",\n".join(f"{pad}  {toml_value(v, indent + 1)}" for v in value)
        return "[\n" + inner + f",\n{pad}]"
    raise TypeError(f"cannot write {type(value)} to TOML")


def zensical_toml(cfg, site_id, nav):
    site = cfg["sites"][site_id]
    portals = [{"id": k, "name": v["title"], "url": site_url(cfg, k)} for k, v in cfg["sites"].items()]
    repo_url = f"https://github.com/{cfg.get('github_owner', '')}/{site['repo']}"
    prefix = site_prefix(site)
    project = {
        "site_name": f"{site['title']} · Nerdience",   # short: fits the mobile header
        "site_url": site_url(cfg, site_id),
        "site_description": site.get("description", ""),
        "site_author": "Nerdience Technologies",
        "copyright": "Copyright &copy; 2026 Nerdience Technologies Private Limited &middot; Internal use only",
        "repo_url": repo_url,
        "repo_name": f"{cfg.get('github_owner', '')}/{site['repo']}",
        "edit_uri": "edit/main/docs/" + (prefix + "/" if prefix else ""),
        "docs_dir": "docs",
        "site_dir": "site",
        "extra_css": ["assets/nerdience/nerdience.css"],
    }
    lines = ["# GENERATED by kit/scripts/generate_site.py from kit/portals.yml and docs/. Do not edit.", "",
             "[project]"]
    lines += [f"{k} = {toml_value(v)}" for k, v in project.items()]
    lines += [f"nav = {toml_value(nav)}", ""]
    lines.append((THEME / "zensical.base.toml").read_text(encoding="utf-8").rstrip())
    lines += ["", "[project.extra]", "generator = false",
              f"portal = {toml_value(site_id)}",
              f"home_url = {toml_value(cfg['front_door'].rstrip('/') + '/home/?choose')}",
              f"portals = {toml_value(portals)}", ""]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ related documents
def add_related(docs_dir, limit=4):
    """Append 'Related documents' to every page: shared tags (x2) + same folder (x1)."""
    pages = []
    for page in docs_dir.rglob("*.md"):
        rel = page.relative_to(docs_dir)
        if page.name == "index.md" or rel.parts[0] in SKIP_DIRS:
            continue
        meta, _ = read_doc(page)
        if not meta or meta.get("utility_page"):
            continue
        tags = {str(t).lower() for t in meta.get("tags") or [] if str(t).lower() not in GENERIC_TAGS}
        pages.append((page, tags, doc_title(page)))
    for page, tags, _ in pages:
        scored = []
        for other, other_tags, title in pages:
            if other == page:
                continue
            score = 2 * len(tags & other_tags) + (1 if other.parent == page.parent else 0)
            if score:
                scored.append((-score, title.lower(), other, title))
        if not scored:
            continue
        lines = ["", "## Related documents", ""]
        for _, _, other, title in sorted(scored)[:limit]:
            link = os.path.relpath(other, page.parent).replace(os.sep, "/")
            lines.append(f"- [{title}]({link})")
        text = page.read_text(encoding="utf-8").rstrip() + "\n" + "\n".join(lines) + "\n"
        page.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------ stage
def site_files(docs_root, site_id, sites):
    """Every file under docs/ that belongs to this site (by longest folder match)."""
    for path in sorted(docs_root.rglob("*")):
        if path.is_file() and site_for(path.relative_to(docs_root).as_posix(), sites) == site_id:
            yield path


def stage(cfg, site_id, root=None, build_root=None):
    root = root or repo_root()
    docs_root = root / "docs"
    build_root = build_root or root / "build"
    sites = repo_sites(cfg, cfg["sites"].get(site_id, {}).get("repo"))
    if site_id not in sites:
        raise SystemExit(f"'{site_id}' is not a site in kit/portals.yml")
    prefix = site_prefix(sites[site_id])
    src = docs_root / prefix if prefix else docs_root
    out = build_root / site_id
    if out.exists():
        shutil.rmtree(out)
    docs_out = out / "docs"
    files = list(site_files(docs_root, site_id, sites))
    if not any(p.suffix == ".md" for p in files):
        raise SystemExit(f"site '{site_id}' has no pages (folders: {sites[site_id]['folders']})")
    for path in files:
        target = docs_out / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    if not (docs_out / "index.md").exists():
        (docs_out / "index.md").write_text(generated_index(docs_out, docs_out), encoding="utf-8")
    nav = build_nav(docs_out)
    recent = recently_updated(src, docs_out, root=root)
    add_related(docs_out)
    finish_indexes(docs_out, sites[site_id], recent)
    mark_overdue(docs_out)
    shutil.copytree(THEME / "assets", docs_out / "assets", dirs_exist_ok=True)
    shutil.copytree(THEME / "overrides", out / "overrides")
    (docs_out / "_headers").write_text(HEADERS, encoding="utf-8")
    (out / "zensical.toml").write_text(zensical_toml(cfg, site_id, nav), encoding="utf-8")
    return out


def main(argv):
    cfg = load_config()
    root = repo_root()
    for site_id in argv or list(repo_sites(cfg, repo_name(root))):
        out = stage(cfg, site_id, root)
        pages = sum(1 for _ in (out / "docs").rglob("*.md"))
        print(f"staged {site_id}: {pages} pages -> build/{site_id}")


if __name__ == "__main__":
    main(sys.argv[1:])
