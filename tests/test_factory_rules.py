"""Rules: §7.3 refusals through `check` and `rule start` with the file unchanged (acceptance 2),
the rule commands, and the guarded write of §7.4."""

import json
import os
import threading

from factory import ruleset
from tests.factory_base import FactoryTestCase, utc

ALL4 = ["fb:kotleta", "ig:kotleta", "linkedin", "x"]


class ActivationRefusalTests(FactoryTestCase):
    """Each case: a draft rule that fails one §7.3 check. `rule start` refuses it with the
    message and leaves rules.json byte-identical; `check` lists the same message once the
    rule is active (written by hand)."""

    def setUp(self):
        super().setUp()
        self.clock.now = utc(2026, 11, 10, 8, 0)
        self.folder("photos", "photo")
        for i in range(1, 4):
            self.stock_package("photos", f"00{i}-p")
        self.folder("texts", "text")
        self.stock_package("texts", "001-t", {"facebook": {"text": "t"}, "x": {"text": "t"}})

    def assert_refused(self, rules, rule_id, message, limits=None):
        self.write_rules(rules, limits)
        before = self.rules_hash()
        code, out, err = self.factory("rule", "start", rule_id)
        self.assertEqual(code, 2, out + err)
        self.assertIn("rules.json is unchanged", err)
        self.assertIn(message, err)
        self.assertEqual(self.rules_hash(), before)
        # the same function behind `check` once the rule is active
        doc = self.rules_doc()
        for r in doc["rules"]:
            if r["id"] == rule_id:
                r["status"], r["active_since"] = "active", "2026-11-01T00:00:00Z"
        self.write_rules(doc["rules"], doc.get("limits"))
        before = self.rules_hash()
        code, out, err = self.factory("check")
        self.assertEqual(code, 2, out + err)
        self.assertIn(message, err)
        self.assertEqual(self.rules_hash(), before)

    def draft(self, rid="new", folder="photos", targets=None, days=("mon",), hours=("10:00",)):
        return self.rule(rid, folder, targets or ["fb:kotleta"], list(days), list(hours),
                         status="draft")

    def test_1_folder_missing(self):
        self.assert_refused([self.draft(folder="nothere")], "new",
                            "folder 'nothere' does not exist in the stock")

    def test_1_no_ready_package(self):
        self.folder("empty")
        self.stock_package("empty", "001-e", approved=False)
        self.assert_refused([self.draft(folder="empty")], "new",
                            "folder 'empty' has no ready package for fb:kotleta")

    def test_2_unknown_target(self):
        self.assert_refused([self.draft(targets=["fb:nobody"])], "new",
                            "target fb:nobody is unknown")

    def test_2_missing_variable_names(self):
        values = dict(self.env_values)
        del values["X_API_KEY"]
        self.write_env(values)
        self.assert_refused([self.draft(targets=["x"])], "new",
                            "target x: missing X_API_KEY in the env file")

    def test_2_linkedin_token_expired(self):
        values = dict(self.env_values, LINKEDIN_TOKEN_EXPIRES_AT="2026-11-01T00:00:00Z")
        self.write_env(values)
        self.assert_refused([self.draft(targets=["linkedin"])], "new",
                            "target linkedin: LinkedIn token expired")

    def test_3_text_lane_cannot_feed_instagram(self):
        self.assert_refused([self.draft(folder="texts", targets=["ig:kotleta"])], "new",
                            "folder 'texts' is a text lane and cannot feed Instagram")

    def test_4_min_gap(self):
        rules = [self.rule("old", "photos", ["fb:kotleta"], ["mon"], ["10:00"]),
                 self.draft(hours=("11:00",))]
        self.assert_refused(rules, "new", "facebook: 2026-11-16 10:00 CET (old) and "
                                          "2026-11-16 11:00 CET (new) are 1 h apart; the "
                                          "minimum gap is 3 h")

    def test_4_max_per_day(self):
        rules = [self.draft(hours=("08:00", "14:00", "20:00"))]
        self.assert_refused(rules, "new", "facebook: 3 posts on 2026-11-16 at 08:00 (new), "
                                          "14:00 (new), 20:00 (new); the maximum is 2 a day",
                            limits={"facebook": {"max_per_day": 2}})

    def test_5_x_budget(self):
        self.ledger_spent("4.600")
        rules = [self.draft(targets=["x"], days=("mon", "wed", "fri"))]
        # $4.60 spent. Wed 11th takes 001 ($0.215 -> 4.815). Fri 13th would take 002 and pass
        # the cap: over budget, X skipped, so 002 stays free for X and every later X-only slot
        # offers it again, as the runner would. The projection counts 002 once: $0.430.
        self.write_rules(rules)
        code, _, err = self.factory("rule", "start", "new")
        self.assertEqual(code, 2)
        self.assertIn("X November: $4.600 spent + $0.430 planned = $5.030 of $5.00", err)
        self.assert_refused(rules, "new", "X November: $4.600 spent + $0.430 planned")

    def test_a_clean_rule_starts_and_check_passes(self):
        self.write_rules([self.draft()])
        code, out, err = self.factory("rule", "start", "new")
        self.assertEqual((code, err), (0, ""))
        rule = self.rules_doc()["rules"][0]
        self.assertEqual((rule["status"], rule["active_since"]), ("active", "2026-11-10T08:00:00Z"))
        code, out, err = self.factory("check")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("ok", out)


class CheckStockTests(FactoryTestCase):
    def test_invalid_and_duplicate_packages_are_problems(self):
        self.folder("a")
        self.stock_package("a", "001-x")
        self.stock_package("a", "002-y", {"x": {"text": "y" * 300}})
        self.folder("b")
        self.stock_package("b", "001-x")      # same id as a/001-x
        os.makedirs(os.path.join(self.content, "packages"))
        with open(os.path.join(self.content, "packages", "one-off.json"), "w") as fh:
            json.dump({"schema": 1, "id": "002-dup", "variants": {"x": {"text": "t"}}}, fh)
        self.stock_package("b", "002-dup")
        self.write_rules([self.rule("r", "a", ["x"], ["mon"], ["10:00"], status="draft")])
        code, out, err = self.factory("check")
        self.assertEqual(code, 2)
        self.assertIn("a/002-y.json: needs fixing: x: text is 300 weighted characters", err)
        self.assertIn("a/001-x.json: needs fixing: duplicate id '001-x' (also b/001-x.json)", err)
        self.assertIn("duplicate id '002-dup' (also packages/one-off.json)", err)

    def test_broken_rules_file_is_reported(self):
        os.makedirs(self.content, exist_ok=True)
        for text, needle in (("{", "not valid UTF-8 JSON"),
                             ('{"schema": 1, "rules": [{"id": "BAD"}]}', "id must match"),
                             ('{"schema": 1, "limits": {"x": {"min_gap_hours": NaN}}}',
                              "min_gap_hours must be a number"),
                             ('{"schema": 1, "limits": {"x": {"max_per_day": 1e999}}}',
                              "max_per_day must be a whole number"),
                             ('{"schema": 1, "rules": [{"id": "a", "folder": "f", "targets": '
                              '["fb:k"], "days": ["mon"], "hours": ["05:00"], "timezone": '
                              '"/etc/localtime"}]}', "hours must be"),
                             ('{"schema": 1, "rules": [{"id": "a", "folder": "f", "targets": '
                              '["fb:k"], "days": ["mon"], "hours": ["10:00"], "timezone": '
                              '"../../etc/passwd"}]}', "timezone must be an IANA zone")):
            with open(os.path.join(self.content, "rules.json"), "w") as fh:
                fh.write(text)
            code, out, err = self.factory("check")
            self.assertEqual(code, 2, text)
            self.assertIn(needle, err, text)
            self.assertNotIn("Traceback", out + err)

    def test_notes_do_not_fail_the_check(self):
        self.folder("a")
        self.stock_package("a", "001-x", approved=False)
        code, out, err = self.factory("check")
        self.assertEqual(code, 0, err)
        self.assertIn("a/001-x.json: not approved", out)


class RuleCommandTests(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.clock.now = utc(2026, 11, 10, 8, 0)
        self.folder("quotes")
        self.stock_package("quotes", "001-q")

    def test_new_set_start_stop(self):
        code, out, err = self.factory("rule", "new", "quotes")
        self.assertEqual((code, err), (0, ""))
        rule = self.rules_doc()["rules"][0]
        self.assertEqual(rule, {"id": "quotes", "folder": "quotes", "targets": ALL4,
                                "days": ["mon", "wed", "fri"], "hours": ["10:00"],
                                "timezone": "Europe/Berlin", "status": "draft"})
        self.assertEqual(os.stat(os.path.join(self.content, "rules.json")).st_mode & 0o777, 0o600)
        code, _, err = self.factory("rule", "set", "quotes", "--hours", "19:00,09:00",
                                    "--days", "fri,mon", "--targets", "fb:kotleta")
        self.assertEqual((code, err), (0, ""))
        rule = self.rules_doc()["rules"][0]
        self.assertEqual((rule["hours"], rule["days"], rule["targets"]),
                         (["09:00", "19:00"], ["mon", "fri"], ["fb:kotleta"]))
        self.assertEqual(self.factory("rule", "start", "quotes")[0], 0)
        self.assertEqual(self.rules_doc()["rules"][0]["status"], "active")
        code, out, _ = self.factory("rule", "stop", "quotes")
        self.assertEqual(code, 0)
        self.assertEqual(self.rules_doc()["rules"][0]["status"], "draft")
        self.assertNotIn("active_since", self.rules_doc()["rules"][0])

    def test_editing_an_active_rule_is_checked_again(self):
        self.write_rules([self.rule("r", "quotes", ["fb:kotleta"], ["mon"], ["10:00"])])
        before = self.rules_hash()
        code, _, err = self.factory("rule", "set", "r", "--hours", "10:00,11:00")
        self.assertEqual(code, 2)
        self.assertIn("minimum gap is 3 h", err)
        self.assertEqual(self.rules_hash(), before)

    def test_bad_values_are_refused_without_a_traceback(self):
        self.factory("rule", "new", "quotes")
        before = self.rules_hash()
        for args in (("--hours", "25:00"), ("--days", "funday"), ("--timezone", "Mars/Base"),
                     ("--targets", "tiktok"), ("--folder", "../etc"), ("--hours", "")):
            code, out, err = self.factory("rule", "set", "quotes", *args)
            self.assertEqual(code, 2, args)
            self.assertNotIn("Traceback", out + err)
        self.assertEqual(self.rules_hash(), before)
        self.assertEqual(self.factory("rule", "new", "quotes")[0], 2)
        self.assertEqual(self.factory("rule", "start", "nope")[0], 2)


class GuardedWriteTests(FactoryTestCase):
    def test_a_stale_revision_is_refused(self):
        path = os.path.join(self.content, "rules.json")
        rs = ruleset.load(path)
        base = rs.revision
        self.assertEqual(base, ruleset.ABSENT)
        rs.rules.append(ruleset.Rule("a", "f", ("x",), ("mon",), ("10:00",), "UTC"))
        ruleset.write(path, rs, base)
        with self.assertRaises(ruleset.RevisionMismatch):
            ruleset.write(path, rs, base)        # the file moved on since `base`
        self.assertEqual([r.id for r in ruleset.load(path).rules], ["a"])

    def test_concurrent_writers_from_one_revision_land_once(self):
        path = os.path.join(self.content, "rules.json")
        ruleset.write(path, ruleset.RuleSet(), ruleset.ABSENT)
        base = ruleset.load(path).revision
        results = []

        def writer(rid):
            rs = ruleset.load(path)
            rs.rules.append(ruleset.Rule(rid, "f", ("x",), ("mon",), ("10:00",), "UTC"))
            try:
                ruleset.write(path, rs, base)
                results.append("ok")
            except ruleset.RevisionMismatch:
                results.append("mismatch")
        threads = [threading.Thread(target=writer, args=(f"r{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ["mismatch"] * 3 + ["ok"])
        self.assertEqual(len(ruleset.load(path).rules), 1)
        self.assertEqual([f for f in os.listdir(self.content) if ".tmp-" in f], [])
