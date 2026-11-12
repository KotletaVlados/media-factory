"""The profile writer's real output is accepted by its reader and prompt builder."""
import os
from factory.authoring import profile
from factory.authoring.common import Refusal
from tests.base import PosterTestCase
from tests.panel_fixture import AUTHOR_PROFILE


class ProfileTest(PosterTestCase):
    def test_empty_save_load_prompt_and_permissions(self):
        content = os.path.join(self.root, "content")
        self.assertIn("not filled in", profile.prompt(profile.load(content)))
        self.assertFalse(os.path.exists(content))
        profile.save(content, AUTHOR_PROFILE, self.clock())
        data = profile.load(content)
        for name, _, _, _ in profile.FIELDS:
            self.assertEqual(profile.value(data, name), profile.value(AUTHOR_PROFILE, name))
            self.assertIn(profile.value(data, name), profile.prompt(data))
        self.assertEqual(os.stat(os.path.join(content, "profile.json")).st_mode & 0o777, 0o600)

    def test_limits_and_wrong_types_never_change_saved_data(self):
        profile.save(self.root, AUTHOR_PROFILE, self.clock())
        before = profile.load(self.root)
        for bad in ({"who": "x" * 601}, {"who": []}, {"audience": []}, {"audience": {"x": 2**20000}}):
            with self.assertRaises(Refusal):
                profile.save(self.root, bad, self.clock())
            self.assertEqual(profile.load(self.root), before)
        os.unlink(os.path.join(self.root, "profile.json"))
        os.symlink(self.env_path, os.path.join(self.root, "profile.json"))
        with self.assertRaises(OSError):
            profile.load(self.root)
