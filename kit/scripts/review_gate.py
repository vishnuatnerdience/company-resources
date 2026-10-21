"""Review gate: refuse to deploy anything that skipped review (PDF section 5).

GitHub enforces branch protection and "require review from Code Owners" on
private repositories only with a paid plan. This script is the free
substitute. It runs at the start of the deploy workflow, after a push to main,
and fails (so nothing is published) unless ALL of these are true:

  1. the pushed commit was merged from a pull request (no direct pushes);
  2. that pull request's "validate" check (pr-checks.yml) passed;
  3. at least REQUIRED_APPROVALS people other than the author approved it;
  4. if REQUIRE_CODE_OWNER_APPROVAL is "true": every changed file has an
     approval from one of its owners in CODEOWNERS (the last matching rule
     wins, as on GitHub).

Only each reviewer's latest review counts, so a withdrawn approval
("changes requested" afterwards) does not count. The PR author never counts
as an approver, even if they own the files.

Owners in CODEOWNERS are ROLES (e.g. @engineering-leads, as in the plan).
On a personal GitHub account there are no teams, so the people holding each
role are listed in .github/code-owner-roles.yml. Entries starting with "TODO"
are placeholders and never match anyone. Org teams (@org/team) also work.

Lint mode (run in pr-checks.yml):  python scripts/review_gate.py --lint

Environment (set by deploy.yml):
  GH_TOKEN, REPO (owner/name), SHA
  REQUIRED_APPROVALS            default 1
  REQUIRE_CODE_OWNER_APPROVAL   default "true"
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pathspec

API = "https://api.github.com"


# ---------------------------------------------------------------- GitHub API
def api(path, token):
    """GET a GitHub API path, following pagination for list results."""
    url, out = f"{API}/{path}", None
    while url:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            link = resp.headers.get("Link", "")
        if isinstance(data, list):
            out = (out or []) + data
        else:
            return data
        url = next((p.split(";")[0].strip("<> ") for p in link.split(",") if 'rel="next"' in p), None)
    return out


# ---------------------------------------------------------------- CODEOWNERS
def load_codeowners(text):
    """Return [(PathSpec, [owners])] in file order."""
    rules = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        spec = pathspec.PathSpec.from_lines("gitwildmatch", [pattern])
        rules.append((pattern, spec, [o.lower() for o in owners]))
    return rules


def owners_for(path, rules):
    """Owners of a file: the LAST matching rule wins (GitHub behaviour)."""
    owners = None
    for _pattern, spec, rule_owners in rules:
        if spec.match_file(path):
            owners = rule_owners
    return owners or []


ROLES_FILE = Path(".github/code-owner-roles.yml")


def load_roles(text):
    """{role: [usernames]} from code-owner-roles.yml; TODO placeholders dropped."""
    import yaml
    data = yaml.safe_load(text) or {}
    return {role.lower(): [u.lower().lstrip("@") for u in (users or [])
                           if not str(u).upper().startswith("TODO")]
            for role, users in data.items()}


def is_placeholder_only(role, raw_roles):
    return all(str(u).upper().startswith("TODO") for u in (raw_roles.get(role) or []))


def team_members(owner, fetch, roles=None):
    """'@role' -> role members; '@org/team' -> team members via the API."""
    name = owner.lstrip("@").lower()
    if "/" not in name:
        if roles is not None and name in roles:
            return set(roles[name])
        return {name}
    org, team = name.split("/", 1)
    try:
        return {m["login"].lower() for m in fetch(f"orgs/{org}/teams/{team}/members")}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"::error::Cannot read members of team {owner} (HTTP {e.code}). "
                         "Give the workflow token read:org access or list users in CODEOWNERS.")


# ---------------------------------------------------------------- the gate
def evaluate(repo, sha, fetch, codeowners_text, required_approvals=1, require_owner=True, roles=None):
    """Return (ok, message). `fetch(path)` performs a GitHub API GET."""
    pulls = [p for p in fetch(f"repos/{repo}/commits/{sha}/pulls") if p.get("merged_at")]
    if not pulls:
        return False, (f"Commit {sha[:7]} was pushed directly to main, not merged from a pull "
                       "request. It will NOT be deployed. Open a pull request instead.")
    pr = pulls[0]
    num, author, head = pr["number"], pr["user"]["login"].lower(), pr["head"]["sha"]

    runs = fetch(f"repos/{repo}/commits/{head}/check-runs")["check_runs"]
    validate = [r for r in runs if r["name"] == "validate"]
    if not validate or any(r["conclusion"] != "success" for r in validate):
        return False, f"Pull request #{num} was merged without passing 'Pull Request Checks'. It will NOT be deployed."

    latest = {}
    for review in fetch(f"repos/{repo}/pulls/{num}/reviews"):   # chronological
        who = review["user"]["login"].lower()
        if who != author and review["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[who] = review["state"]
    approvers = {who for who, state in latest.items() if state == "APPROVED"}
    if len(approvers) < required_approvals:
        return False, (f"Pull request #{num} has {len(approvers)} approval(s) from people other than "
                       f"its author; {required_approvals} required. It will NOT be deployed.")

    if require_owner:
        rules = load_codeowners(codeowners_text)
        files = [f["filename"] for f in fetch(f"repos/{repo}/pulls/{num}/files")]
        cache, missing = {}, []
        for path in files:
            owners = owners_for(path, rules)
            if not owners:
                continue                      # no owner defined: approval count is enough
            allowed = set()
            for o in owners:
                if o not in cache:
                    cache[o] = team_members(o, fetch, roles)
                allowed |= cache[o]
            if not (approvers & allowed):
                missing.append(f"{path} (owners: {' '.join(owners)})")
        if missing:
            return False, (f"Pull request #{num} is missing code-owner approval for "
                           f"{len(missing)} file(s): " + "; ".join(missing[:10]) +
                           ". It will NOT be deployed.")

    approved = f"approved by {', '.join(sorted(approvers))}" if approvers else "no approvals required"
    return True, (f"Review gate passed: PR #{num} by {author}, checks passed, {approved}"
                  + (", code owners satisfied." if require_owner else "."))


def find_codeowners():
    return next((p for p in (Path(".github/CODEOWNERS"), Path("CODEOWNERS"), Path("docs/CODEOWNERS"))
                 if p.exists()), None)


def lint():
    """CI check: every CODEOWNERS owner is a defined role (or an org team)."""
    import yaml
    co = find_codeowners()
    if co is None or not ROLES_FILE.exists():
        raise SystemExit(f"::error::Need CODEOWNERS and {ROLES_FILE}.")
    raw = {k.lower(): v for k, v in (yaml.safe_load(ROLES_FILE.read_text()) or {}).items()}
    errors, used = [], set()
    for pattern, _spec, owners in load_codeowners(co.read_text()):
        for o in owners:
            name = o.lstrip("@")
            if not o.startswith("@"):
                errors.append(f"{pattern}: owner '{o}' must start with @")
            elif "/" in name:
                continue                                  # org team, resolved via API
            elif name not in raw:
                errors.append(f"{pattern}: '{o}' is not a role in {ROLES_FILE} (typo?)")
            else:
                used.add(name)
    for e in errors:
        print(f"::error::{e}")
    for role in sorted(used):
        if is_placeholder_only(role, raw):
            print(f"::warning::Role @{role} has only TODO placeholders; nobody can approve its files yet.")
    for role in sorted(set(raw) - used):
        print(f"::warning::Role @{role} is defined but not used in CODEOWNERS.")
    if errors:
        sys.exit(1)
    print(f"CODEOWNERS check passed: {len(used)} roles used, all defined in {ROLES_FILE}.")


def main():
    if "--lint" in sys.argv:
        return lint()
    token, repo, sha = os.environ["GH_TOKEN"], os.environ["REPO"], os.environ["SHA"]
    required = int(os.environ.get("REQUIRED_APPROVALS", "1"))
    require_owner = os.environ.get("REQUIRE_CODE_OWNER_APPROVAL", "true").lower() == "true"
    codeowners = find_codeowners()
    if require_owner and codeowners is None:
        raise SystemExit("::error::REQUIRE_CODE_OWNER_APPROVAL is true but no CODEOWNERS file was found.")
    roles = load_roles(ROLES_FILE.read_text()) if ROLES_FILE.exists() else None
    ok, msg = evaluate(repo, sha, lambda path: api(path, token),
                       codeowners.read_text() if codeowners else "", required, require_owner, roles)
    print(msg if ok else f"::error::{msg}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
