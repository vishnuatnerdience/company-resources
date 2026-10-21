"""Validate the repository before anything is built (runs on every pull request).

    python ../company-resources/kit/scripts/validate.py     (from a content repository)

Every page belongs to one site (kit/portals.yml, longest folder match), so a
NEW folder needs no configuration: it joins the repository's main site and is
checked against that site's allowed classifications.

ERRORS (fail CI):
  - portals.yml problems: missing title/repo/access/classifications, bad access
    value, a repository without exactly one main site (folders: [""]), a folder
    claimed twice, a mapped folder that does not exist, unknown login_order site
  - missing or unparsable frontmatter, or a missing required field
  - classification not allowed on the page's site (a `restricted` page in an
    all-employee site is refused)
  - status not a lifecycle value; last_reviewed not a date or in the future;
    review_cycle_days not a positive whole number; `order` not a whole number
  - status: approved without a real owner, approved_by and approved_on (A4)

WARNINGS (shown, do not fail):
  - review overdue (last_reviewed + review_cycle_days is in the past)
  - owner empty or "TBD" on a page that is not approved yet
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portal import (SKIP_DIRS, load_config, read_doc, repo_name, repo_root,  # noqa: E402
                    repo_sites, site_for)

REQUIRED = ["title", "owner", "department", "classification", "status",
            "version", "last_reviewed", "review_cycle_days", "tags"]
CLASSIFICATIONS = {"public", "internal", "restricted", "confidential"}
STATUSES = {"draft", "review", "approved", "review-due", "deprecated"}
PLACEHOLDER_OWNERS = {"", "tbd", "todo", "none"}


def as_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def check_config(cfg):
    errors = []
    sites = cfg.get("sites") or {}
    if not sites:
        errors.append("portals.yml: no sites defined")
    for key in ("email_domain", "project_prefix", "host_suffix", "admins_group", "front_door"):
        if not cfg.get(key):
            errors.append(f"portals.yml: '{key}' is missing")
    for sid in cfg.get("login_order") or []:
        if sid not in sites:
            errors.append(f"portals.yml: login_order names unknown site '{sid}'")
    defaults, seen = {}, {}
    for sid, s in sites.items():
        where = f"portals.yml: {sid}"
        for key in ("repo", "title"):
            if not s.get(key):
                errors.append(f"{where}: '{key}' is missing")
        access = s.get("access")
        if access != "everyone" and not (isinstance(access, list) and access and all(isinstance(g, str) for g in access)):
            errors.append(f"{where}: 'access' must be 'everyone' or a list of Cloudflare Access group names")
        allowed = s.get("classifications")
        if not allowed or not set(allowed) <= CLASSIFICATIONS:
            errors.append(f"{where}: 'classifications' must be a non-empty list from {sorted(CLASSIFICATIONS)}")
        if "confidential" in (allowed or []):
            errors.append(f"{where}: 'confidential' is not allowed in the portal (plan §4)")
        for folder in s.get("folders") or [""]:
            key = (s.get("repo"), folder)
            if key in seen:
                errors.append(f"{where}: folder '{folder}' is already used by site '{seen[key]}'")
            seen[key] = sid
            if folder == "":
                defaults.setdefault(s.get("repo"), []).append(sid)
    for repo in {s.get("repo") for s in sites.values()}:
        if len(defaults.get(repo, [])) != 1:
            errors.append(f"portals.yml: repository '{repo}' needs exactly one site with folders: [\"\"] "
                          f"(found {defaults.get(repo, [])})")
    return errors


def check_doc(path, allowed_classifications, today):
    """Return (errors, warnings) for one Markdown file."""
    errors, warnings = [], []
    meta, _ = read_doc(path)
    if meta is None:
        return ["missing or invalid frontmatter (--- yaml --- at the top)"], []
    missing = [f for f in REQUIRED if f not in meta]
    if missing:
        errors.append("missing required field(s): " + ", ".join(missing))

    status = str(meta.get("status", "")).lower()
    if "status" in meta and status not in STATUSES:
        errors.append(f"status '{meta['status']}' must be one of {sorted(STATUSES)}")

    cls = str(meta.get("classification", "")).lower()
    if "classification" in meta and cls not in allowed_classifications:
        errors.append(f"classification '{meta['classification']}' is not allowed on this site "
                      f"(allowed: {', '.join(allowed_classifications)})")

    reviewed = as_date(meta.get("last_reviewed")) if "last_reviewed" in meta else None
    if "last_reviewed" in meta and reviewed is None:
        errors.append(f"last_reviewed '{meta['last_reviewed']}' must be a date like 2026-10-21")
    elif reviewed and reviewed > today:
        errors.append(f"last_reviewed {reviewed} is in the future")

    cycle = meta.get("review_cycle_days")
    if "review_cycle_days" in meta and not (isinstance(cycle, int) and not isinstance(cycle, bool) and cycle > 0):
        errors.append(f"review_cycle_days '{cycle}' must be a positive whole number")
    elif reviewed and isinstance(cycle, int) and (today - reviewed).days > cycle:
        warnings.append(f"review overdue: last reviewed {reviewed}, cycle {cycle} days")

    if "order" in meta and not (isinstance(meta["order"], int) and not isinstance(meta["order"], bool)):
        errors.append(f"order '{meta['order']}' must be a whole number")

    owner_missing = str(meta.get("owner", "")).strip().lower() in PLACEHOLDER_OWNERS
    if status == "approved":
        if owner_missing:
            errors.append("approved page needs a real owner (not empty or TBD)")
        if not str(meta.get("approved_by", "")).strip():
            errors.append("approved page needs 'approved_by' (who in the department approved it)")
        if as_date(meta.get("approved_on", "")) is None:
            errors.append("approved page needs 'approved_on' as a date")
    elif owner_missing and "owner" in meta:
        warnings.append("owner is empty or TBD")
    return errors, warnings


def validate(root=None, cfg=None, today=None, repo=None):
    """Return (errors, warnings) as lists of 'path: message' strings."""
    cfg = cfg or load_config()
    root = Path(root or repo_root())
    repo = repo or repo_name(root)
    today = today or date.today()
    docs_root = root / "docs"
    errors, warnings = check_config(cfg), []
    sites = repo_sites(cfg, repo)
    if not sites:
        return errors + [f"portals.yml: no site uses repo '{repo}'"], warnings
    if not docs_root.is_dir():
        return errors + ["docs/ folder is missing"], warnings
    for sid, s in sites.items():
        for folder in s["folders"]:
            if folder and not (docs_root / folder).is_dir():
                errors.append(f"portals.yml: site '{sid}' maps docs/{folder}/, which does not exist")

    for path in sorted(docs_root.rglob("*.md")):
        rel = path.relative_to(docs_root).as_posix()
        if rel.split("/")[0] in SKIP_DIRS:
            continue
        sid = site_for(rel, sites)
        allowed = [c.lower() for c in sites[sid].get("classifications") or []]
        e, w = check_doc(path, allowed, today)
        errors += [f"docs/{rel}: {m} [site: {sid}]" for m in e]
        warnings += [f"docs/{rel}: {m}" for m in w]
    return errors, warnings


def main():
    errors, warnings = validate()
    for w in warnings:
        print(f"::warning::{w}")
    for e in errors:
        print(f"::error::{e}")
    print(f"\nValidation {'FAILED' if errors else 'passed'}: {len(errors)} error(s), {len(warnings)} warning(s).")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
