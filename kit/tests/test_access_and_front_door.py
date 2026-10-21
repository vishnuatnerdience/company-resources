import json
import re
import unittest

from helpers import config

import render_front_door as r
import smoke
import sync_access as s
from portal import load_config

GROUPS = {"engineering": "g-eng", "management": "g-mgt", "people-ops": "g-ppl", "portal-admins": "g-adm"}


class SyncPlanTest(unittest.TestCase):
    def test_login_order_sites_deny_to_next_others_to_no_access(self):
        wanted = {d["host"]: d for d in s.desired(config())}
        self.assertEqual(wanted["nerdience-engineering.pages.dev"]["deny_url"],
                         "https://door.example/home/next/?from=engineering")
        self.assertEqual(wanted["nerdience-hr-general.pages.dev"]["deny_url"],
                         "https://door.example/home/next/?from=hr-general")
        self.assertEqual(wanted["nerdience-management.pages.dev"]["deny_url"],
                         "https://door.example/no-access/?portal=management")

    def test_repo_filter_and_includes(self):
        hosts = {d["host"]: d["include"] for d in s.desired(config(), "company-hr-general")}
        self.assertNotIn("nerdience-engineering.pages.dev", hosts)
        self.assertEqual(hosts["nerdience-hr-general.pages.dev"],
                         [("email_domain", "nerdience.com"), ("group", "portal-admins")])
        self.assertEqual(hosts["*.nerdience-management.pages.dev"], [("group", "portal-admins")])

    def test_empty_account_plan_and_missing_group(self):
        actions, errors, _ = s.plan(config(), {"apps": [], "groups": GROUPS, "projects": set()},
                                    "company-hr-general")
        self.assertEqual(errors, [])
        self.assertEqual(sum(a["op"] == "create_app" for a in actions), 6)
        _, errors, _ = s.plan(config(), {"apps": [], "groups": {"portal-admins": "g"}, "projects": set()},
                              "company-hr-general")
        self.assertTrue(any("management" in e and "do not exist" in e for e in errors))


class SmokeTest(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(smoke.verdict(302, "https://t.cloudflareaccess.com/cdn-cgi/access/login/x"), "ok")
        self.assertEqual(smoke.verdict(200, ""), "PUBLIC")
        self.assertTrue(smoke.verdict(302, "https://evil.example/").startswith("error"))
        self.assertEqual(smoke.verdict(0, "getaddrinfo failed", before_deploy=True), "ok")


class FrontDoorTest(unittest.TestCase):
    def test_cards_and_data_come_from_portals_yml(self):
        cfg = config()
        cards = r.cards(cfg)
        for title in ("Engineering", "HR &amp; General", "Management"):
            self.assertIn(title, cards)
        data = json.loads(re.search(r">(.*)</script>", r.data(cfg)).group(1))
        self.assertEqual(data["order"], ["engineering", "hr-general"])
        self.assertEqual(data["sites"]["management"]["url"], "https://nerdience-management.pages.dev/")

    def test_real_front_door_is_up_to_date(self):
        stale = [p for p, content in r.outputs(load_config()).items()
                 if not p.exists() or p.read_text(encoding="utf-8") != content]
        self.assertEqual(stale, [], "run kit/scripts/render_front_door.py")


if __name__ == "__main__":
    unittest.main()
