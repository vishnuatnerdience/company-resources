"""Write the generated parts of the front door from kit/portals.yml and kit/templates/.

    python kit/scripts/render_front_door.py           # update public/ (run from company-resources)
    python kit/scripts/render_front_door.py --check   # CI: fail if public/ is out of date

Generated (between <!-- generated:NAME:start --> / :end markers, rest is hand-written):
  public/home/index.html        department cards + sign-in order data
  public/home/next/index.html   sign-in order data (where Access sends a denied person)
  public/index.html             "Contribute" email address
  public/downloads/template.md  copy of kit/templates/template.md
  public/downloads/example.md   copy of kit/templates/example.md

Portal addresses only go into /home/ pages, which are behind Cloudflare Access;
the public pages never list them.
"""
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portal import KIT, load_config, site_url  # noqa: E402

PUBLIC = KIT.parent / "public"
ICONS = {
    "code": "m8.7 7.1 1.4 1.4L6.6 12l3.5 3.5-1.4 1.4L3.8 12l4.9-4.9Zm6.6 0 4.9 4.9-4.9 4.9-1.4-1.4 3.5-3.5-3.5-3.5 1.4-1.4Z",
    "people": "M12 3 2 8l10 5 8-4v6h2V8L12 3Zm-6 9.2V16c0 1.7 2.7 3 6 3s6-1.3 6-3v-3.8l-6 3-6-3Z",
    "chart": "M4 19h16v2H2V3h2v16Zm3-2V11h3v6H7Zm5 0V7h3v10h-3Zm5 0v-4h3v4h-3Z",
    "folder": "M3 6a2 2 0 0 1 2-2h4.6l2 2H19a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6Zm2 2v10h14V8H5Z",
}


def cards(cfg):
    items = []
    for sid, s in cfg["sites"].items():
        icon = ICONS.get(s.get("icon"), ICONS["folder"])
        audience = s.get("audience") or ("Everyone at Nerdience" if s["access"] == "everyone" else "Restricted")
        items.append(
            "      <li>\n"
            f'        <a class="card" href="{site_url(cfg, sid)}">\n'
            f'          <span class="card__icon"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">'
            f'<path fill="currentColor" d="{icon}"/></svg></span>\n'
            f'          <h3 class="card__title">{html.escape(s["title"])}</h3>\n'
            f'          <span class="card__who">{html.escape(audience)}</span>\n'
            f'          <p class="card__text">{html.escape(s.get("description", ""))}</p>\n'
            f'          <span class="card__go">Open {html.escape(s["title"])}</span>\n'
            "        </a>\n"
            "      </li>")
    return '    <ul class="cards">\n' + "\n".join(items) + "\n    </ul>"


def data(cfg):
    payload = {
        "order": [sid for sid in cfg.get("login_order") or [] if sid in cfg["sites"]],
        "sites": {sid: {"title": s["title"], "url": site_url(cfg, sid)} for sid, s in cfg["sites"].items()},
    }
    return ('  <script type="application/json" id="nd-portals">'
            + json.dumps(payload, ensure_ascii=False).replace("</", "<\\/") + "</script>")


def contribute_email(cfg):
    email = html.escape(cfg["contribute_email"])
    return f'          <a class="mail" href="mailto:{email}?subject=Portal%20document">{email}</a>'


def replace_block(text, name, content, path):
    pattern = re.compile(rf"(<!-- generated:{name}:start -->\n).*?(\n[ \t]*<!-- generated:{name}:end -->)", re.S)
    if not pattern.search(text):
        raise SystemExit(f"{path}: markers for '{name}' not found")
    return pattern.sub(lambda m: m.group(1) + content + m.group(2), text)


def outputs(cfg):
    """{path: new content} for every generated file."""
    out = {}
    home = PUBLIC / "home" / "index.html"
    text = home.read_text(encoding="utf-8")
    text = replace_block(text, "cards", cards(cfg), home)
    out[home] = replace_block(text, "data", data(cfg), home)
    nxt = PUBLIC / "home" / "next" / "index.html"
    out[nxt] = replace_block(nxt.read_text(encoding="utf-8"), "data", data(cfg), nxt)
    landing = PUBLIC / "index.html"
    out[landing] = replace_block(landing.read_text(encoding="utf-8"), "email", contribute_email(cfg), landing)
    for name in ("template.md", "example.md"):
        out[PUBLIC / "downloads" / name] = (KIT / "templates" / name).read_text(encoding="utf-8")
    return out


def main(argv):
    cfg = load_config()
    stale = []
    for path, content in outputs(cfg).items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        if "--check" in argv:
            stale.append(path.relative_to(KIT.parent).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"updated {path.relative_to(KIT.parent).as_posix()}")
    if stale:
        print("::error::Front door is out of date with kit/portals.yml: " + ", ".join(stale)
              + ". Run: python kit/scripts/render_front_door.py")
        sys.exit(1)
    print("Front door is up to date." if "--check" in argv else "Done.")


if __name__ == "__main__":
    main(sys.argv[1:])
