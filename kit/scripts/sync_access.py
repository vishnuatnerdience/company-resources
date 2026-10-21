"""Make Cloudflare match kit/portals.yml: one Pages project + Access apps per site.

Run from a content repository (manages that repository's sites only):

    python ../company-resources/kit/scripts/sync_access.py            # DRY RUN (default)
    python ../company-resources/kit/scripts/sync_access.py --apply    # make the changes

Environment: CF_ACCOUNT_ID and CF_ACCESS_TOKEN (needs Access: Apps and Policies
Edit, Access: Groups Read, Pages Edit). Without them the dry run assumes an empty
account and prints the full plan ("offline").

For each site it ensures:
  1. Pages project  <prefix><site>  (production branch main);
  2. Access app on  <prefix><site>.<host_suffix>  allowing the site's groups
     (or everyone @email_domain) + the admins group. Denied users go to the
     front door: /home/next/?from=<site> for sites in login_order (so the sign-in
     flow can try the next portal), else /no-access/?portal=<site>;
  3. Access app on  *.<prefix><site>.<host_suffix>  (preview URLs): admins only.

Safety rules:
  - it NEVER deletes apps, policies or projects (unknown ones are only reported);
  - it never changes WHO is in a group (managed in the Cloudflare dashboard);
  - a group named in portals.yml that does not exist is an error, not created;
  - run it BEFORE the first deploy of a new site, so it is never
    reachable without an Access app (deploy.yml also probes this).

NOTE: written against the Cloudflare v4 API documentation (access/apps,
access/policies, access/groups, pages/projects). Not yet run against the live
account: try the dry run first, then --apply on a test site.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portal import hostname, load_config, project_name, repo_name, repo_sites  # noqa: E402

API = "https://api.cloudflare.com/client/v4"


# ------------------------------------------------------------------ desired state (pure)
def deny_url(cfg, site_id):
    door = cfg["front_door"].rstrip("/")
    if site_id in (cfg.get("login_order") or []):
        return f"{door}/home/next/?from={site_id}"
    return f"{door}/no-access/?portal={site_id}"


def desired(cfg, repo=None):
    """List of dicts describing every project/app that should exist (this repo's sites)."""
    admins = cfg["admins_group"]
    sites = repo_sites(cfg, repo) if repo else cfg["sites"]
    out = []
    for sid, s in sites.items():
        host = hostname(cfg, sid)
        if s["access"] == "everyone":
            include = [("email_domain", cfg["email_domain"])]
        else:
            include = [("group", g) for g in s["access"]]
        include = sorted(set(include) | {("group", admins)})
        out.append({"site": sid, "project": project_name(cfg, sid), "host": host,
                    "app_name": f"Portal - {s['title']}", "include": include,
                    "deny_url": deny_url(cfg, sid)})
        out.append({"site": sid, "project": None, "host": f"*.{host}",
                    "app_name": f"Portal - {s['title']} (previews)",
                    "include": [("group", admins)], "deny_url": deny_url(cfg, sid)})
    return out


def symbolic(include_json, groups_by_id):
    """API include rules -> sorted [(kind, value)] for comparison."""
    out = []
    for rule in include_json or []:
        if "email_domain" in rule:
            out.append(("email_domain", rule["email_domain"]["domain"]))
        elif "group" in rule:
            out.append(("group", groups_by_id.get(rule["group"]["id"], "?" + rule["group"]["id"])))
        else:
            out.append(("other", json.dumps(rule, sort_keys=True)))
    return sorted(out)


def plan(cfg, state, repo=None):
    """Compare desired vs current. state = {apps: [...], groups: {name: id}, projects: {names}}.

    Returns (actions, errors, notes). Never produces a delete.
    """
    actions, errors, notes = [], [], []
    groups_by_id = {v: k for k, v in state["groups"].items()}
    apps_by_host = {}
    for app in state["apps"]:
        for host in [app.get("domain")] + [d.get("uri") for d in app.get("destinations") or []]:
            if host:
                apps_by_host[host] = app
    wanted_hosts = set()
    for want in desired(cfg, repo):
        wanted_hosts.add(want["host"])
        missing = [v for k, v in want["include"] if k == "group" and v not in state["groups"]]
        if missing and not state.get("offline"):
            errors.append(f"{want['app_name']}: Access group(s) {missing} do not exist. "
                          "Create them in the Cloudflare dashboard first.")
            continue
        if want["project"] and want["project"] not in state["projects"]:
            actions.append({"op": "create_project", "name": want["project"]})
        app = apps_by_host.get(want["host"])
        if app is None:
            actions.append({"op": "create_app", **want})
            continue
        policies = app.get("policies") or []
        current = sorted({r for p in policies if p.get("decision") == "allow"
                          for r in symbolic(p.get("include"), groups_by_id)})
        if current != want["include"]:
            if len(policies) != 1:
                errors.append(f"{want['host']}: app '{app.get('name')}' has {len(policies)} policies; "
                              "fix by hand (sync only manages apps with exactly one policy)")
            else:
                actions.append({"op": "update_policy", "policy_id": policies[0]["id"],
                                "policy_name": policies[0].get("name", ""), "host": want["host"],
                                "include": want["include"], "was": current})
    for host, app in apps_by_host.items():
        prefix = cfg["project_prefix"]
        if host not in wanted_hosts and prefix in host and cfg["host_suffix"] in host:
            notes.append(f"app '{app.get('name')}' on {host} is not in portals.yml "
                         "(left untouched; delete by hand if obsolete)")
    return actions, errors, notes


def describe(action):
    def rules(inc):
        return ", ".join(f"{k}={v}" for k, v in inc)
    if action["op"] == "create_project":
        return f"+ create Pages project {action['name']}"
    if action["op"] == "create_app":
        return f"+ create Access app '{action['app_name']}' on {action['host']} allowing [{rules(action['include'])}]"
    return (f"~ update policy '{action['policy_name']}' on {action['host']}: "
            f"[{rules(action['was'])}] -> [{rules(action['include'])}]")


# ------------------------------------------------------------------ Cloudflare API
class Cloudflare:
    def __init__(self, account, token):
        self.base, self.token = f"{API}/accounts/{account}", token

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())["result"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise SystemExit(f"Cloudflare API {method} {path}: HTTP {e.code} {detail}")

    def list(self, path):
        items, page = [], 1
        while True:
            sep = "&" if "?" in path else "?"
            batch = self.call("GET", f"{path}{sep}page={page}&per_page=50")
            items += batch or []
            if not batch or len(batch) < 50:
                return items
            page += 1

    def state(self):
        return {"apps": self.list("/access/apps"),
                "groups": {g["name"]: g["id"] for g in self.list("/access/groups")},
                "projects": {p["name"] for p in self.list("/pages/projects")}}

    def rules_json(self, include, groups):
        return [{"email_domain": {"domain": v}} if k == "email_domain" else {"group": {"id": groups[v]}}
                for k, v in include]

    def apply(self, action, groups, session):
        if action["op"] == "create_project":
            self.call("POST", "/pages/projects", {"name": action["name"], "production_branch": "main"})
        elif action["op"] == "create_app":
            policy = self.call("POST", "/access/policies", {
                "name": f"{action['app_name']} - allow", "decision": "allow",
                "include": self.rules_json(action["include"], groups)})
            self.call("POST", "/access/apps", {
                "name": action["app_name"], "type": "self_hosted", "domain": action["host"],
                "destinations": [{"type": "public", "uri": action["host"]}],
                "session_duration": session, "app_launcher_visible": False,
                "custom_deny_url": action["deny_url"],
                "policies": [{"id": policy["id"], "precedence": 1}]})
        elif action["op"] == "update_policy":
            self.call("PUT", f"/access/policies/{action['policy_id']}", {
                "name": action["policy_name"], "decision": "allow",
                "include": self.rules_json(action["include"], groups)})


def main(argv):
    apply = "--apply" in argv
    cfg = load_config()
    account, token = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_ACCESS_TOKEN")
    if account and token:
        cf = Cloudflare(account, token)
        state = cf.state()
    elif apply:
        raise SystemExit("--apply needs CF_ACCOUNT_ID and CF_ACCESS_TOKEN.")
    else:
        cf, state = None, {"apps": [], "groups": {}, "projects": set(), "offline": True}
        print("OFFLINE dry run (no Cloudflare credentials): assuming an empty account.\n")

    actions, errors, notes = plan(cfg, state, repo_name())
    for n in notes:
        print(f"note: {n}")
    for a in actions:
        print(describe(a))
    for e in errors:
        print(f"::error::{e}")
    if not actions and not errors:
        print("Cloudflare already matches portals.yml.")
    if errors:
        sys.exit(1)
    if apply and actions:
        for a in actions:
            cf.apply(a, state["groups"], cfg.get("session_duration", "24h"))
            print(f"done: {describe(a)}")
    elif actions:
        print(f"\nDry run: {len(actions)} change(s). Re-run with --apply to make them.")


if __name__ == "__main__":
    main(sys.argv[1:])
