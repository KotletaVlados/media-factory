import json
import os
import unicodedata

from poster import package
from tests.base import PosterTestCase, make_jpeg


class PackageTests(PosterTestCase):
    def load(self, path):
        return package.load(path, self.library)

    def test_schema_1_accepted_with_library_and_path_images(self):
        self.image("lib.jpg", make_jpeg(100, 100))
        os.makedirs(os.path.join(self.pkg_dir, "photos"))
        self.image("own.jpg", make_jpeg(10, 10), os.path.join(self.pkg_dir, "photos"))
        path = self.package({"facebook": {"text": "a", "image": "lib.jpg"},
                             "linkedin": {"text": "b", "image": "photos/own.jpg"},
                             "x": {"text": "c", "image": None}},
                            name="2026-11-09-theme", meta={"source": "chat"})
        pkg = self.load(path)
        self.assertEqual(pkg.id, "2026-11-09-theme")
        self.assertEqual(pkg.variants["facebook"].image_path, os.path.join(self.library, "lib.jpg"))
        self.assertEqual(pkg.variants["linkedin"].image_path,
                         os.path.join(self.pkg_dir, "photos", "own.jpg"))
        self.assertIsNone(pkg.variants["x"].image_path)
        self.assertEqual(pkg.meta, {"source": "chat"})

    def test_absolute_path_and_dotdot_allowed(self):
        p = self.image("abs.jpg", make_jpeg(10, 10), self.root)
        path = self.package({"x": {"text": "a", "image": p}, "linkedin": {"text": "b", "image": "../abs.jpg"}})
        pkg = self.load(path)
        self.assertEqual(pkg.variants["x"].image_path, p)
        self.assertEqual(pkg.variants["linkedin"].image_path, p)

    def problems(self, path):
        with self.assertRaises(package.PackageError) as cm:
            self.load(path)
        return " | ".join(cm.exception.problems)

    def test_unknown_keys_refused(self):
        p = self.problems(self.package({"x": {"txt": "typo"}}, extra=1))
        self.assertIn("unknown top-level key(s): extra", p)
        self.assertIn("x: unknown key(s) txt", p)
        self.assertIn("unknown network 'tiktok'", self.problems(self.package({"tiktok": {"text": "a"}})))

    def test_schema_must_be_1(self):
        for schema in (2, "1", True, None):
            path = self.package({"x": {"text": "a"}}, schema=schema)
            self.assertIn("schema must be 1", self.problems(path))

    def test_empty_text_and_empty_variants_refused(self):
        self.assertIn("text is required", self.problems(self.package({"x": {"text": "   "}})))
        self.assertIn("text is required", self.problems(self.package({"x": {"text": 5}})))
        self.assertIn("non-empty", self.problems(self.package({})))

    def test_id_pattern(self):
        self.assertIn("id must match", self.problems(self.package({"x": {"text": "a"}}, id="Bad Id")))
        self.assertIn("id must match", self.problems(self.package({"x": {"text": "a"}}, name="UPPER")))
        pkg = self.load(self.package({"x": {"text": "a"}}, id="ok.id-1"))
        self.assertEqual(pkg.id, "ok.id-1")

    def test_missing_image_and_bad_library_names(self):
        self.assertIn("not found (library", self.problems(self.package({"x": {"text": "a", "image": "nope.jpg"}})))
        self.assertIn("may not start with '.'", self.problems(self.package({"x": {"text": "a", "image": ".hidden.jpg"}})))
        os.makedirs(os.path.join(self.library, "dir.jpg"))
        self.assertIn("not found", self.problems(self.package({"x": {"text": "a", "image": "dir.jpg"}})))
        self.assertIn("must be a string", self.problems(self.package({"x": {"text": "a", "image": 3}})))

    def test_invalid_json_and_missing_file(self):
        bad = os.path.join(self.pkg_dir, "bad.json")
        with open(bad, "w") as fh:
            fh.write("{not json")
        self.assertIn("not valid", self.problems(bad))
        self.assertIn("not found", self.problems(os.path.join(self.pkg_dir, "none.json")))
        with open(bad, "w") as fh:
            json.dump([1, 2], fh)
        self.assertIn("JSON object", self.problems(bad))

    def test_nfc_normalisation_and_exact_text(self):
        decomposed = "Café  two  spaces\n\nend "
        pkg = self.load(self.package({"x": {"text": decomposed}}))
        self.assertEqual(pkg.variants["x"].text, unicodedata.normalize("NFC", decomposed))
        self.assertTrue(pkg.variants["x"].text.endswith("end "))
