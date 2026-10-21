import tempfile
import tomllib
import unittest
from datetime import date
from pathlib import Path

from helpers import config, make_repo, page

import generate_site as g
import validate as v
from portal import repo_sites, site_for, site_prefix

HR_FILES = {
    "index.md": page("HR & General"),
    "people/index.md": page("People", order=1),
    "people/leave.md": page("Leave Policy", tags="[people, leave]"),
    "people/holidays.md": page("Holidays", tags="[people, leave]"),
    "people/performance/index.md": page("Performance", classification="restricted"),
    "people/performance/reviews.md": page("Review Process", classification="restricted"),
    "management/index.md": page("Management"),
    "management/strategy.md": page("Company Strategy", classification="restricted"),
    "brand-new-folder/first.md": page("First Page"),           # editor created a folder
}


class FolderMappingTest(unittest.TestCase):
    def setUp(self):
        self.sites = repo_sites(config(), "company-hr-general")

    def test_longest_folder_wins(self):
        self.assertEqual(site_for("people/leave.md", self.sites), "hr-general")
        self.assertEqual(site_for("people/performance/reviews.md", self.sites), "performance")
        self.assertEqual(site_for("management/strategy.md", self.sites), "management")
        self.assertEqual(site_for("managementx/a.md", self.sites), "hr-general")   # not a prefix match

    def test_new_folder_joins_main_site(self):
        self.assertEqual(site_for("brand-new-folder/first.md", self.sites), "hr-general")

    def test_single_folder_site_is_rooted_at_its_folder(self):
        self.assertEqual(site_prefix(self.sites["management"]), "management")
        self.assertEqual(site_prefix(self.sites["hr-general"]), "")


class StageTest(unittest.TestCase):
    def setUp(self):
        self.root = make_repo(HR_FILES)
        self.build = Path(tempfile.mkdtemp())

    def staged(self, site):
        out = g.stage(config(), site, self.root, self.build)
        return out, {p.relative_to(out / "docs").as_posix() for p in (out / "docs").rglob("*.md")}

    def test_main_site_excludes_other_sites_folders(self):
        out, pages = self.staged("hr-general")
        self.assertIn("brand-new-folder/first.md", pages)
        self.assertNotIn("management/strategy.md", pages)
        self.assertFalse(any(p.startswith("people/performance") for p in pages))
        text = " ".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.suffix in {".md", ".toml"})
        self.assertNotIn("Company Strategy", text)
        self.assertNotIn("Review Process", text)

    def test_folder_site_contains_only_its_folder(self):
        _, pages = self.staged("management")
        self.assertEqual(pages, {"index.md", "strategy.md"})
        _, pages = self.staged("performance")
        self.assertEqual(pages, {"index.md", "reviews.md"})

    def test_nav_and_cards_are_generated(self):
        out, _ = self.staged("hr-general")
        nav = tomllib.loads((out / "zensical.toml").read_text(encoding="utf-8"))["project"]["nav"]
        labels = [next(iter(item)) for item in nav]
        self.assertEqual(labels[:3], ["Home", "People", "Brand New Folder"])
        home = (out / "docs" / "index.md").read_text(encoding="utf-8")
        self.assertIn('for="__search"', home)
        self.assertIn("Brand New Folder", home)

    def test_related_documents_use_tags_and_folder(self):
        out, _ = self.staged("hr-general")
        leave = (out / "docs" / "people" / "leave.md").read_text(encoding="utf-8")
        self.assertIn("## Related documents", leave)
        self.assertIn("[Holidays](holidays.md)", leave)

    def test_switcher_lists_every_site_and_edit_link_points_to_folder(self):
        out, _ = self.staged("management")
        project = tomllib.loads((out / "zensical.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["edit_uri"], "edit/main/docs/management/")
        self.assertEqual(project["repo_url"], "https://github.com/acme/company-hr-general")
        self.assertEqual([p["id"] for p in project["extra"]["portals"]],
                         ["engineering", "hr-general", "management", "performance"])

    def test_overdue_pages_are_flagged(self):
        docs = self.root / "docs"
        (docs / "people" / "old.md").write_text(page("Old", last_reviewed='"2025-01-01"'), encoding="utf-8")
        g.mark_overdue(docs, today=date(2026, 10, 21))
        self.assertIn("review_overdue: true", (docs / "people" / "old.md").read_text(encoding="utf-8"))


class ValidateTest(unittest.TestCase):
    def run_validate(self, files):
        return v.validate(make_repo(files), config(), date(2026, 10, 21), "company-hr-general")

    def test_mapped_repo_passes(self):
        errors, _ = self.run_validate(HR_FILES)
        self.assertEqual(errors, [])

    def test_restricted_page_refused_in_everyone_site(self):
        errors, _ = self.run_validate({**HR_FILES, "people/salaries.md": page("Salaries", classification="restricted")})
        self.assertTrue(any("salaries.md" in e and "'restricted' is not allowed" in e and "hr-general" in e
                            for e in errors))

    def test_same_page_allowed_in_restricted_site(self):
        errors, _ = self.run_validate({**HR_FILES, "management/budget.md": page("Budget", classification="restricted")})
        self.assertEqual(errors, [])

    def test_approved_needs_approval_record(self):
        errors, _ = self.run_validate({**HR_FILES, "people/x.md": page("X", status="approved", owner='"TBD"')})
        text = " ".join(errors)
        for expected in ("real owner", "approved_by", "approved_on"):
            self.assertIn(expected, text)

    def test_config_errors(self):
        cfg = config()
        cfg["sites"]["extra-main"] = {"repo": "company-hr-general", "title": "X", "folders": [""],
                                      "access": "all", "classifications": ["confidential"]}
        cfg["login_order"].append("nope")
        text = " ".join(v.check_config(cfg))
        for expected in ("exactly one site", "'access' must be", "'confidential' is not allowed",
                         "unknown site 'nope'", "already used"):
            self.assertIn(expected, text)

    def test_mapped_folder_must_exist(self):
        files = {k: val for k, val in HR_FILES.items() if not k.startswith("management/")}
        errors, _ = self.run_validate(files)
        self.assertTrue(any("docs/management/, which does not exist" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
