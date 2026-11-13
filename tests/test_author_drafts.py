"""Draft writes, recovery, bounded cache and hostile paths."""
import os
import threading
from unittest import mock
from factory.authoring import drafts, photos
from factory.authoring.common import Refusal
from tests.base import PosterTestCase
from tests import panel_fixture as pf


class DraftTest(PosterTestCase):
    def setUp(self):
        super().setUp()
        self.fx = pf.build_empty(os.path.join(self.root, "panel"))
        orig = pf.make_photo(32, 24, 1)
        self.photo = pf.store_photo(self.fx, "my-photos", orig, orig, orig, "sample.jpg")
        self.store = drafts.Store(self.fx.paths.content, self.clock, self.fx.machine_tz)

    def create(self, key=True):
        with mock.patch("factory.authoring.drafts.secrets.token_hex", return_value="abcd"):
            return self.store.create(self.fx.paths.stock, "my-photos", self.photo, key)

    def test_writer_reader_restart_and_modes(self):
        d = self.create()
        self.assertRegex(d["id"], r"^2026-11-09-my-photos-abcd$")
        self.assertEqual(d["topics_auto"], "pending")
        self.assertEqual(self.store.load(d["id"]), d)
        other = drafts.Store(self.fx.paths.content, self.clock, self.fx.machine_tz)
        self.assertEqual(other.load(d["id"]), d)
        self.assertEqual(os.stat(self.store.path(d["id"])).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(self.store.path(d["id"]), "draft.json")).st_mode & 0o777, 0o600)

    def test_atomic_field_updates_keep_both_fields_and_cache_rebuilds(self):
        d = self.create()
        self.assertEqual(self.store.summaries()[0]["topic"], "")
        gate = threading.Barrier(2)
        def change(key, value):
            gate.wait()
            self.store.update(d["id"], lambda data: data.update({key: value}))
        ts = [threading.Thread(target=change, args=args) for args in (("topic", "own topic"), ("topics_auto", "done"))]
        for t in ts: t.start()
        for t in ts: t.join(5)
        self.assertEqual(self.store.load(d["id"])["topic"], "own topic")
        self.assertEqual(self.store.load(d["id"])["topics_auto"], "done")
        self.assertEqual(self.store.summaries()[0]["topic"], "own topic")
        with mock.patch.object(self.store, "load", side_effect=AssertionError("cache rebuilt")):
            self.assertEqual(len(self.store.summaries()), 1)

    def test_no_key_cap_and_invalid_photo(self):
        d = self.create(False)
        self.assertEqual(d["topics_auto"], "manual")
        with mock.patch("factory.authoring.drafts.MAX_DRAFTS", 1), self.assertRaisesRegex(Refusal, "500"):
            self.store.create(self.fx.paths.stock, "my-photos", self.photo, True)
        for folder, pid in (("../x", self.photo), ("my-photos", "p-0000000000000000"), ([], self.photo)):
            with self.assertRaises((Refusal, photos.UploadError)):
                self.store.create(self.fx.paths.stock, folder, pid, True)

    def test_traversal_symlinks_and_invalid_mutations(self):
        d = self.create()
        for bad in ("../x", [], "x" * 10000):
            with self.assertRaises(Refusal): self.store.load(bad)
        target = self.store.path(d["id"])
        os.rename(target, target + "-saved")
        os.symlink(target + "-saved", target)
        with self.assertRaises(Refusal): self.store.load(d["id"])
        os.unlink(target)
        os.rename(target + "-saved", target)
        with self.assertRaises(Refusal):
            self.store.update(d["id"], lambda data: data.update(topic=[]))
        self.assertEqual(self.store.load(d["id"])["topic"], "")
        os.rename(self.store.root, self.store.root + "-saved")
        os.symlink(self.store.root + "-saved", self.store.root)
        with self.assertRaises(Refusal): self.store.load(d["id"])


    def test_default_500_cap_is_read_from_persisted_records(self):
        import copy
        d = self.create()
        for n in range(1, 500):
            row = copy.deepcopy(d)
            row["id"] = f"2026-11-09-my-photos-{n:04x}"
            path = os.path.join(self.store.root, row["id"])
            os.mkdir(path, 0o700)
            drafts.atomic(os.path.join(path, "draft.json"), drafts.validate(row))
        fresh = drafts.Store(self.fx.paths.content, self.clock, self.fx.machine_tz)
        self.assertEqual(len(fresh.summaries()), 500)
        with self.assertRaisesRegex(Refusal, "удалите ненужные"):
            fresh.create(self.fx.paths.stock, "my-photos", self.photo, True)


class SentDraftTest(DraftTest):
    """The D′ states and fields of authoring.md §17.2, as every writer stores them."""

    def sent(self, state="partial", outcome=None, **extra):
        import copy
        if not hasattr(self, "_draft"):
            self._draft = self.create()
        d = copy.deepcopy(self._draft)
        targets = ["fb:kotleta", "ig:kotleta", "linkedin", "x"]
        attempt = {"started": "2026-11-09T10:00:00Z", "ended": "2026-11-09T10:01:00Z",
                   "targets": targets, "offset": 12, "exit": 1,
                   "outcome": outcome if outcome is not None else {
                       "fb:kotleta": {"status": "published", "url": "https://example.com/p"},
                       "linkedin": {"status": "failed", "error": "HTTP 401"}}}
        data = dict(d, state=state, publish={"package": f"packages/{d['id']}.json",
                                             "targets": targets, "attempts": [attempt]}, **extra)
        return d, data

    def test_each_writer_value_is_read_back(self):
        for state in ("publishing", "partial", "published"):
            d, data = self.sent(state, focus=[0.5, 0.2],
                                refused={"lines": ["x: X budget"], "ts": "2026-11-09T10:00:00Z"})
            drafts.atomic(os.path.join(self.store.path(d["id"]), "draft.json"), drafts.validate(data))
            self.assertEqual(self.store.load(d["id"]), data)
        drafts.atomic(os.path.join(self.store.path(d["id"]), "draft.json"), drafts.validate(self._draft))
        self.store.update(d["id"], lambda x: x.update(focus=[0, 1], refused={"lines": [], "ts": "2026-11-09T10:00:00Z"}))
        self.assertEqual(self.store.load(d["id"])["focus"], [0, 1])

    def test_limits_and_shapes(self):
        bad = [
            dict(state="publishing", publish=None),
            dict(focus=[0.5, 1.5]), dict(focus=[0.5]), dict(focus=[True, 0.5]),
            dict(refused={"lines": ["x" * 501], "ts": "2026-11-09T10:00:00Z"}),
            dict(refused={"lines": [], "ts": "soon"}),
        ]
        for extra in bad:
            d, data = self.sent()
            data.update(extra)
            if data.get("publish") is None:
                data.pop("publish")
            with self.assertRaises(Refusal, msg=extra):
                drafts.validate(data)
        d, data = self.sent()
        data["publish"]["attempts"] *= 21
        with self.assertRaises(Refusal):
            drafts.validate(data)
        for outcome in ({"fb:kotleta": {"status": "deleted"}}, {"fb:demo": {"status": "published"}},
                        {"x": {"status": "failed", "error": "e" * 501}}):
            d, data = self.sent(outcome=outcome)
            with self.assertRaises(Refusal, msg=outcome):
                drafts.validate(data)
        d, data = self.sent()
        with self.assertRaises(Refusal):
            drafts.validate(dict(data, state="sent"))

    def test_sent_drafts_refuse_edits_and_have_stage_words(self):
        d, data = self.sent("published", outcome={})
        drafts.atomic(os.path.join(self.store.path(d["id"]), "draft.json"), drafts.validate(data))
        with self.assertRaisesRegex(Refusal, "черновик уже отправлен"):
            self.store.update(d["id"], lambda x: x.update(topic="x"))
        self.store.update(d["id"], lambda x: x.update(focus=[0.1, 0.1]), sent_ok=True)
        self.assertEqual(drafts.stage(self.store.load(d["id"])), "published")
        for state, outcome, word in (("partial", None, "partial"), ("publishing", {}, "publishing"),
                                     ("partial", {"fb:kotleta": {"status": "interrupted"}}, "interrupted")):
            _, data = self.sent(state, outcome)
            self.assertEqual(drafts.stage(drafts.validate(data)), word)
        self.assertEqual(self.store.summaries()[0]["state"], "published")
