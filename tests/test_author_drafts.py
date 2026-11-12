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
        with self.assertRaisesRegex(Refusal, "500"):
            fresh.create(self.fx.paths.stock, "my-photos", self.photo, True)
