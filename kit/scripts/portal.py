"""Shared helpers for the portal kit.

The kit lives in company-resources/kit/ and is run FROM a content repository
(company-engineering or company-hr-general):

    cd company-hr-general
    python ../company-resources/kit/scripts/build_all.py

The repository is the current directory (or PORTAL_ROOT); its name (or
PORTAL_REPO) selects its sites in kit/portals.yml.
"""
import os
import re
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parent.parent
CONFIG = KIT / "portals.yml"
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)
SKIP_DIRS = {"assets"}                       # theme assets, not documents


def repo_root():
    return Path(os.environ.get("PORTAL_ROOT", Path.cwd())).resolve()


def repo_name(root=None):
    return os.environ.get("PORTAL_REPO") or (root or repo_root()).name


def load_config(path=CONFIG):
    """portals.yml as a dict; sites sorted by `order`, then id."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sites = cfg.get("sites") or {}
    for site in sites.values():
        site["folders"] = [str(f).strip("/") for f in site.get("folders") or [""]]
    cfg["sites"] = dict(sorted(sites.items(), key=lambda kv: (kv[1].get("order", 99), kv[0])))
    return cfg


def repo_sites(cfg, repo):
    return {k: v for k, v in cfg["sites"].items() if v.get("repo") == repo}


def project_name(cfg, site):
    return f"{cfg['project_prefix']}{site}"


def hostname(cfg, site):
    return f"{project_name(cfg, site)}.{cfg['host_suffix']}"


def site_url(cfg, site):
    return f"https://{hostname(cfg, site)}/"


def site_for(rel_path, sites):
    """Site id owning a path under docs/ (longest matching folder wins)."""
    rel = str(rel_path).replace("\\", "/").strip("/")
    best, best_len = None, -1
    for sid, site in sites.items():
        for folder in site["folders"]:
            if folder == "" or rel == folder or rel.startswith(folder + "/"):
                if len(folder) > best_len:
                    best, best_len = sid, len(folder)
    return best


def site_prefix(site):
    """Folder stripped when staging: a site made of ONE folder gets it as its root."""
    folders = [f for f in site["folders"] if f]
    return folders[0] if len(site["folders"]) == 1 and len(folders) == 1 else ""


def split_frontmatter(text):
    """Return (meta dict or None, body). None means no/invalid frontmatter block."""
    m = FRONTMATTER.match(text)
    if not m:
        return None, text
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, text
    return (meta if isinstance(meta, dict) else None), m.group(2)


def read_doc(path):
    return split_frontmatter(Path(path).read_text(encoding="utf-8"))


def title_from_name(name):
    """'sales-and-delivery' -> 'Sales and Delivery' (used when a folder has no index.md)."""
    small = {"and", "or", "of", "the", "a", "to", "in", "for"}
    words = Path(name).stem.replace("_", "-").split("-")
    return " ".join(w if i and w in small else w[:1].upper() + w[1:] for i, w in enumerate(words))


def doc_title(path):
    meta, body = read_doc(path)
    if meta and meta.get("title"):
        return str(meta["title"])
    h1 = re.search(r"^# (.+)$", body, flags=re.M)
    return h1.group(1).strip() if h1 else title_from_name(Path(path).name)


def doc_order(path):
    meta, _ = read_doc(path)
    try:
        return int((meta or {}).get("order", 999))
    except (TypeError, ValueError):
        return 999


if __name__ == "__main__":
    # "<site> <pages project>" per line for this repository, for shell loops in CI.
    config = load_config()
    for sid in repo_sites(config, repo_name()):
        print(sid, project_name(config, sid))
