"""One-off: convert a v2 content repository to the shared kit (run once per repo).

    cd company-hr-general
    python ../company-resources/kit/scripts/migrate_repo.py

What it does (all visible in `git status` / `git diff` afterwards):
  - removes per-repo tooling now provided by the kit: zensical.toml, overrides/,
    scripts/, docs/assets/nerdience/ (theme), docs/no-access.md (Cloudflare now
    denies to the front door);
  - index pages keep frontmatter + H1 + description only; card grids and
    "Contents" lists are generated at build time from now on;
  - top-level sections get `order:` so the plan's order (§3) is kept;
  - the document template becomes a valid page that SHOWS the template.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portal import KIT, load_config, repo_name, repo_root, repo_sites, split_frontmatter  # noqa: E402

GENERATED_START = re.compile(
    r'^(<div class="nd-hero"|<p class="nd-section-label"|<div class="nd-grid"|## Contents\s*$)', re.M)
SECTION_ORDER = {   # implementation plan §3
    "company-engineering": ["development", "code-review", "architecture", "infrastructure",
                            "devops", "sre", "security", "delivery", "templates"],
    "company-hr-general": ["company", "people", "operations", "management",
                           "sales-and-delivery", "templates", "faq"],
}
REMOVE = ["zensical.toml", "overrides", "scripts", "docs/assets/nerdience", "docs/no-access.md"]


def clean_index(text, title=None, description=None):
    head = re.match(r"\A---\r?\n.*?\r?\n---\r?\n", text, re.S)
    head = head.group(0) if head else ""
    meta, body = split_frontmatter(text)
    if title:
        head = re.sub(r"^title:.*$", f"title: {title}", head, count=1, flags=re.M)
    cut = GENERATED_START.search(body)
    body = (body[:cut.start()] if cut else body).strip()
    if not re.search(r"^# ", body, flags=re.M):
        body = f"# {title or (meta or {}).get('title', '')}\n\n{description or ''}".strip()
    return head + "\n" + body + "\n"


def set_order(index, n):
    text = index.read_text(encoding="utf-8")
    if not re.search(r"^order:", text, flags=re.M):
        index.write_text(text.replace("\n---\n", f"\norder: {n}\n---\n", 1), encoding="utf-8")


def main():
    root, cfg = repo_root(), load_config()
    repo = repo_name(root)
    sites = repo_sites(cfg, repo)
    main_site = next(s for s in sites.values() if "" in s["folders"])
    for rel in REMOVE:
        if (root / rel).exists():
            subprocess.run(["git", "rm", "-r", "-q", "--", rel], cwd=root, check=True)
    docs = root / "docs"
    for index in docs.rglob("index.md"):
        text = index.read_text(encoding="utf-8")
        if index.parent == docs:
            index.write_text(clean_index(text, main_site["title"], main_site.get("description")), encoding="utf-8")
        else:
            index.write_text(clean_index(text), encoding="utf-8")
    for n, section in enumerate(SECTION_ORDER.get(repo, []), 1):
        if (docs / section / "index.md").exists():
            set_order(docs / section / "index.md", n)
    template = docs / "templates" / "document-template.md"
    if template.exists():
        shutil.copy2(KIT / "templates" / "template-page.md", template)
    print(f"Converted {repo}. Review with: git status && git diff --stat")


if __name__ == "__main__":
    main()
