"""Rules and Files actions (design factory.md §13.3 item 3; brief §3.1 Writes): each action
changes exactly its field, a stale revision is refused, start refuses the §7.3 cases with the
text shown on the row, and nothing but the rules file (or the new folder) is written."""

from __future__ import annotations

import copy
import html
import json
import os
import stat
import unittest

from poster import config
from tests import panel_fixture as pf


class RuleActionsTest(pf.PanelCase):
    def act(self, kind: str, rule: str, **fields):
        return self.post(f"/rules/{kind}", dict(fields, rule=rule, rev=self.revision()))

    def assert_only(self, before: dict, rule_id: str, **changed):
        """The rules file equals `before` except for the named fields of one rule."""
        expected = copy.deepcopy(before)
        for r in expected["rules"]:
            if r["id"] == rule_id:
                for k, v in changed.items():
                    if v is None:
                        r.pop(k, None)
                    else:
                        r[k] = v
        self.assertEqual(self.rules_doc(), expected)

    def other_files(self) -> dict:
        """Every file but the rules file and the lock that fruleset.write takes beside it."""
        h = self.state_hashes()
        h.pop(os.path.relpath(self.fx.paths.rules, self.fx.root))
        h.pop(os.path.join("content", "rules.lock"), None)
        return h

    def test_toggle_a_day(self):
        before, others = self.rules_doc(), self.other_files()
        status, headers, _ = self.act("day", "notes-draft", day="mon")
        self.assertEqual((status, headers["location"]), (303, "/rules#rule-notes-draft"))
        self.assert_only(before, "notes-draft", days=["mon", "thu", "sat"])
        self.act("day", "notes-draft", day="thu")
        self.assert_only(before, "notes-draft", days=["mon", "sat"])
        self.assertEqual(self.other_files(), others)

    def test_select_all_days(self):
        before = self.rules_doc()
        self.assertEqual(self.act("day", "notes-draft", day="all")[0], 303)
        self.assert_only(before, "notes-draft",
                         days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
        self.assertNotIn('value="all"', self.get("/rules")[2].split('id="rule-notes-draft"')[1]
                         .split('id="rule-tips-ig"')[0], "no-op 'select all' is hidden")

    def test_toggle_an_hour(self):
        before = self.rules_doc()
        self.assertEqual(self.act("hour", "notes-draft", hour="08:00")[0], 303)
        self.assert_only(before, "notes-draft", hours=["08:00", "17:00"])

    def test_change_the_zone(self):
        before = self.rules_doc()
        self.assertEqual(self.act("zone", "notes-draft", zone="Europe/Paris")[0], 303)
        self.assert_only(before, "notes-draft", timezone="Europe/Paris")

    def test_start_a_draft_that_passes(self):
        before, others = self.rules_doc(), self.other_files()
        self.assertEqual(self.act("start", "notes-draft")[0], 303)
        self.assert_only(before, "notes-draft", status="active",
                         active_since=config.iso_utc(pf.NOW))
        self.assertEqual(self.other_files(), others)
        self.assertIn("работает с 11 ноября", self.get("/rules")[2])

    def test_stop_an_active_rule(self):
        before = self.rules_doc()
        self.assertEqual(self.act("stop", "city-main")[0], 303)
        self.assert_only(before, "city-main", status="draft", active_since=None)

    def test_start_of_an_active_rule_and_stop_of_a_draft_change_nothing(self):
        before = self.file_hash(self.fx.paths.rules)
        self.assertEqual(self.act("start", "city-main")[0], 303)
        self.assertEqual(self.act("stop", "notes-draft")[0], 303)
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)

    def test_create_a_rule(self):
        before = self.rules_doc()
        p = pf.profile()
        status, headers, _ = self.post("/rules/new", [
            ("rev", self.revision()), ("id", "nature-main"), ("folder", "nature"),
            ("targets", p["facebook"]), ("targets", p["instagram"]), ("days", "mon"),
            ("days", "sun"), ("hours", "09:00"), ("zone", "Europe/Berlin")])
        self.assertEqual((status, headers["location"]), (303, "/rules#rule-nature-main"))
        expected = copy.deepcopy(before)
        expected["rules"].append({"id": "nature-main", "folder": "nature",
                                  "targets": [p["facebook"], p["instagram"]],
                                  "days": ["mon", "sun"], "hours": ["09:00"],
                                  "timezone": "Europe/Berlin", "status": "draft"})
        self.assertEqual(self.rules_doc(), expected)

    def test_new_rule_refusals_keep_the_file(self):
        before = self.file_hash(self.fx.paths.rules)
        status, _, body = self.post("/rules/new", {"rev": self.revision(), "id": "city-main",
                                                   "folder": "city", "targets": "x",
                                                   "days": "mon", "hours": "09:00",
                                                   "zone": "Europe/Berlin"})
        self.assertEqual(status, 409)
        self.assertIn("Правило «city-main» уже есть", body)
        status, _, body = self.post("/rules/new", {"rev": self.revision(), "id": "Bad Id",
                                                   "folder": "city", "targets": "x",
                                                   "days": "mon", "hours": "09:00",
                                                   "zone": "Europe/Berlin"})
        self.assertEqual(status, 409)
        self.assertIn("id must match", html.unescape(body))
        self.assertIn("Новое правило не сохранено", body)
        self.assertIn('<details class="newrule" open', body)
        self.assertIn('value="Bad Id"', body, "the form keeps what was typed")
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)

    def test_stale_revision_is_refused(self):
        rev = self.revision()
        self.assertEqual(self.post("/rules/day", {"rule": "notes-draft", "rev": rev,
                                                  "day": "mon"})[0], 303)
        after = self.file_hash(self.fx.paths.rules)
        # the same form again (a second click, or another tab): the revision is old
        for kind, extra in (("day", {"day": "mon"}), ("hour", {"hour": "08:00"}),
                            ("zone", {"zone": "UTC"}), ("start", {}), ("stop", {})):
            status, _, body = self.post(f"/rules/{kind}", dict(extra, rule="notes-draft", rev=rev))
            self.assertEqual(status, 409, kind)
            self.assertIn("Правила изменились в другом месте — обновите страницу", body)
        status, _, body = self.post("/rules/new", {"rev": rev, "id": "z", "folder": "notes"})
        self.assertEqual(status, 409)
        self.assertEqual(self.file_hash(self.fx.paths.rules), after)

    def test_start_refuses_the_checks_with_the_text_on_the_row(self):
        before, others = self.file_hash(self.fx.paths.rules), self.other_files()
        status, _, body = self.act("start", "tips-ig")
        self.assertEqual(status, 409)
        row = html.unescape(body.split('id="rule-tips-ig"')[1].split("<datalist")[0])
        self.assertIn('role="alert"', row)
        self.assertIn("folder 'tips' is a text lane and cannot feed Instagram", row)
        self.assertIn("folder 'tips' has no ready package for", row)
        self.assertIn("Правило «tips-ig» не изменено", body)
        self.assertIn('href="#rule-tips-ig"', body)
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)
        self.assertEqual(self.other_files(), others)

    def test_start_refuses_a_limit_clash(self):
        # notes-draft at 13:00 Lisbon is 14:00 Berlin on Thursday: 2 h after quotes-main's
        # 12:00 post on LinkedIn, whose minimum gap is 6 h
        doc = self.rules_doc()
        for r in doc["rules"]:
            if r["id"] == "notes-draft":
                r["hours"] = ["13:00"]
        pf._write_json(self.fx.paths.rules, doc)
        before = self.file_hash(self.fx.paths.rules)
        status, _, body = self.act("start", "notes-draft")
        self.assertEqual(status, 409)
        self.assertIn("the minimum gap is 6 h", body)
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)

    def test_an_edit_of_a_running_rule_runs_the_activation_checks(self):
        before = self.file_hash(self.fx.paths.rules)
        status, _, body = self.act("hour", "city-main", hour="11:00")
        self.assertEqual(status, 409)
        row = html.unescape(body.split('id="rule-city-main"')[1].split('id="rule-quotes-main"')[0])
        self.assertIn("linkedin:", row)
        self.assertIn("the minimum gap is 6 h", row)
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)

    def test_invalid_values_are_refused(self):
        before = self.file_hash(self.fx.paths.rules)
        status, _, body = self.act("zone", "notes-draft", zone="Mars/Base")
        self.assertEqual(status, 409)
        self.assertIn("timezone must be an IANA zone name", body)
        status, _, body = self.act("hour", "notes-draft", hour="17:00")   # the only hour
        self.assertEqual(status, 409)
        self.assertIn("hours must be a non-empty list", body)
        self.assertEqual(self.act("day", "notes-draft", day="funday")[0], 400)
        self.assertEqual(self.act("hour", "notes-draft", hour="05:00")[0], 400)
        self.assertEqual(self.act("hour", "notes-draft", hour="9:00")[0], 400)
        status, _, body = self.act("day", "no-such-rule", day="mon")
        self.assertEqual(status, 409)
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)

    def test_a_broken_rules_file_refuses_writes_and_shows_the_error(self):
        with open(self.fx.paths.rules, "w", encoding="utf-8") as fh:
            fh.write('{"schema": 1, "rules": [{"id": "Bad"}]}\n')
        before = self.file_hash(self.fx.paths.rules)
        status, _, body = self.post("/rules/day", {"rule": "Bad", "rev": "x", "day": "mon"})
        self.assertEqual(status, 409)
        self.assertIn("Файл правил с ошибкой", body)
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)


class NewFolderTest(pf.PanelCase):
    def test_creates_the_folder_and_folder_json_only(self):
        before = self.state_hashes()
        status, headers, _ = self.post("/files/new-folder", {"name": "travel", "lane": "photo",
                                                             "title": "  Поездки  "})
        self.assertEqual((status, headers["location"]), (303, "/files?folder=travel"))
        folder = os.path.join(self.fx.paths.stock, "travel")
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o700)
        meta = os.path.join(folder, "folder.json")
        self.assertEqual(stat.S_IMODE(os.stat(meta).st_mode), 0o600)
        self.assertEqual(os.listdir(folder), ["folder.json"])
        with open(meta, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"schema": 1, "title": "Поездки", "lane": "photo"})
        after = self.state_hashes()
        after.pop(os.path.relpath(meta, self.fx.root))
        self.assertEqual(after, before)
        status, _, body = self.get("/files?folder=travel")
        self.assertEqual(status, 200)
        self.assertIn("В папке пока нет пакетов", body)

    def test_refuses_an_existing_name_and_bad_input(self):
        before = self.state_hashes()
        status, _, body = self.post("/files/new-folder", {"name": "city", "lane": "photo"})
        self.assertEqual(status, 409)
        self.assertIn("Папка «city» уже есть", body)
        self.assertIn('<details class="fcard newcard lane-photo" open', body)
        for name, lane in (("../escape", "photo"), ("Travel", "photo"), ("", "photo"),
                           ("a" * 41, "photo"), ("ok-name", "video"), (".hidden", "text")):
            status, _, _ = self.post("/files/new-folder", {"name": name, "lane": lane})
            self.assertEqual(status, 400, (name, lane))
        self.assertEqual(self.state_hashes(), before)
        self.assertFalse(os.path.exists(os.path.join(self.fx.root, "content", "escape")))


class EmptyCreateTest(pf.PanelCase):
    FIXTURE = "empty"

    def test_first_folder_and_first_rule_on_an_empty_factory(self):
        status, _, _ = self.post("/files/new-folder", {"name": "first", "lane": "text"})
        self.assertEqual(status, 303)
        status, _, _ = self.post("/rules/new", {"rev": "absent", "id": "first", "folder": "first",
                                                "targets": "linkedin", "days": "mon",
                                                "hours": "10:00", "zone": "UTC"})
        self.assertEqual(status, 303)
        self.assertEqual(self.rules_doc()["rules"][0]["id"], "first")


if __name__ == "__main__":
    unittest.main()
