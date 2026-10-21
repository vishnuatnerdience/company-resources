import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def page(title, order=None, **extra):
    meta = {"title": title, "owner": "Docs team", "department": "General",
            "classification": "internal", "status": "draft", "version": '"1.0"',
            "last_reviewed": '"2026-10-01"', "review_cycle_days": 90, "tags": "[x]"}
    if order is not None:
        meta["order"] = order
    meta.update(extra)
    lines = "\n".join(f"{k}: {v}" for k, v in meta.items())
    return f"---\n{lines}\n---\n\n# {title}\n\n## Purpose\n\nAbout {title}.\n"


def make_repo(files, name="company-hr-general"):
    """files: {path under docs/: content}. Returns the temp repository root."""
    root = Path(tempfile.mkdtemp()) / name
    for rel, content in files.items():
        path = root / "docs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def config():
    sites = {
        "engineering": {"repo": "company-engineering", "title": "Engineering", "folders": [""],
                        "access": ["engineering"], "classifications": ["internal", "restricted"], "order": 1},
        "hr-general": {"repo": "company-hr-general", "title": "HR & General", "folders": [""],
                       "access": "everyone", "classifications": ["public", "internal"], "order": 2},
        "management": {"repo": "company-hr-general", "title": "Management", "folders": ["management"],
                       "access": ["management"], "classifications": ["internal", "restricted"], "order": 3},
        "performance": {"repo": "company-hr-general", "title": "Performance", "folders": ["people/performance"],
                        "access": ["people-ops"], "classifications": ["restricted"], "order": 4},
    }
    return {"email_domain": "nerdience.com", "project_prefix": "nerdience-", "host_suffix": "pages.dev",
            "admins_group": "portal-admins", "front_door": "https://door.example",
            "github_owner": "acme", "login_order": ["engineering", "hr-general"], "sites": sites}
