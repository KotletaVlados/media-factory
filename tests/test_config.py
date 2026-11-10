import os
import stat

from poster import config
from tests.base import PosterTestCase, REPO_ROOT


class EnvPathTests(PosterTestCase):
    def test_precedence_flag_over_env_over_repo_default(self):
        self.assertEqual(config.resolve_env_path("/a/flag.env", {"MF_ENV_FILE": "/b.env"}), "/a/flag.env")
        self.assertEqual(config.resolve_env_path(None, {"MF_ENV_FILE": "/b.env"}), "/b.env")
        self.assertEqual(config.resolve_env_path(None, {}), os.path.join(REPO_ROOT, ".env"))

    def test_state_dir_default_is_outside_the_repository(self):
        path = config.resolve_state_dir(None, {"HOME": self.home})
        self.assertTrue(path.startswith(self.home))
        real_default = config.resolve_state_dir(None, {"HOME": os.path.expanduser("~")})
        self.assertFalse(os.path.abspath(real_default).startswith(REPO_ROOT + os.sep))
        self.assertEqual(config.resolve_state_dir(None, {"XDG_STATE_HOME": "/x"}),
                         "/x/media-factory/poster")
        self.assertEqual(config.resolve_state_dir("/flag", {"MF_STATE_DIR": "/m"}), "/flag")
        self.assertEqual(config.resolve_state_dir(None, {"MF_STATE_DIR": "/m"}), "/m")

    def test_library_default_is_git_ignored_content_folder(self):
        self.assertEqual(config.resolve_library(None, {}), os.path.join(REPO_ROOT, "content", "images"))
        with open(os.path.join(REPO_ROOT, ".gitignore"), encoding="utf-8") as fh:
            self.assertIn("content/", fh.read().split())

    def test_tests_never_open_the_repo_default(self):
        self.assertNotEqual(self.environ["MF_ENV_FILE"], os.path.join(REPO_ROOT, ".env"))


class ParseTests(PosterTestCase):
    def test_comments_blank_quotes_and_equals_in_value(self):
        env = config.parse_env("# c\n\nA=1\nB='two words'\nC=\"x=y\"\nD=a=b=c\n  E = spaced \n")
        self.assertEqual(env, {"A": "1", "B": "two words", "C": "x=y", "D": "a=b=c", "E": "spaced"})

    def test_malformed_line_reported_by_number_without_content(self):
        with self.assertRaises(config.ConfigError) as cm:
            config.parse_env("A=1\nthis is secret-ish garbage\nB=2\n9X=bad\n")
        msg = str(cm.exception)
        self.assertIn("2, 4", msg)
        self.assertNotIn("garbage", msg)
        self.assertNotIn("bad", msg.replace("content not shown", ""))

    def test_missing_env_file(self):
        with self.assertRaises(config.ConfigError):
            config.load_env(os.path.join(self.root, "nope.env"))


class WriteBackTests(PosterTestCase):
    def test_updates_appends_and_keeps_other_bytes(self):
        original = b"# keep me\r\nA=1\nLINKEDIN_ACCESS_TOKEN=old\n\nZ='quoted value'\nLINKEDIN_ACCESS_TOKEN=dup"
        path = os.path.join(self.root, "w.env")
        with open(path, "wb") as fh:
            fh.write(original)
        os.chmod(path, 0o644)
        config.write_back(path, {"LINKEDIN_ACCESS_TOKEN": "new", "LINKEDIN_PERSON_URN": "urn:li:person:x"})
        with open(path, "rb") as fh:
            data = fh.read()
        self.assertEqual(data, b"# keep me\r\nA=1\nLINKEDIN_ACCESS_TOKEN=new\n\nZ='quoted value'\n"
                               b"LINKEDIN_PERSON_URN=urn:li:person:x\n")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual([f for f in os.listdir(self.root) if ".tmp-" in f], [])

    def test_temp_name_is_covered_by_the_env_ignore_rule(self):
        # a leftover temp copy (kill, power loss) holds every secret: git must ignore it
        import fnmatch
        ignore = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".gitignore")
        with open(ignore) as fh:
            rules = fh.read().split()
        for env_name in (".env", ".env.local"):
            name = config.temp_name(os.path.join(self.root, env_name))
            self.assertTrue(name.startswith(env_name + ".tmp-"), name)
            self.assertTrue(any(fnmatch.fnmatch(name, r) for r in rules if "*" in r), name)

    def test_symlinked_env_file_keeps_its_link(self):
        real = os.path.join(self.root, "real.env")
        link = os.path.join(self.root, "link.env")
        with open(real, "w") as fh:
            fh.write("A=1\n")
        os.symlink(real, link)
        config.write_back(link, {"B": "2"})
        self.assertTrue(os.path.islink(link))
        with open(real) as fh:
            self.assertEqual(fh.read(), "A=1\nB=2\n")

    def test_atomic_replace_leaves_original_on_failure(self):
        path = os.path.join(self.root, "a.env")
        with open(path, "w") as fh:
            fh.write("A=1\n")
        real_replace = os.replace

        def boom(*a):
            raise OSError("disk full")
        os.replace = boom
        try:
            with self.assertRaises(OSError):
                config.write_back(path, {"A": "2"})
        finally:
            os.replace = real_replace
        self.assertIs(os.replace, real_replace)
        with open(path) as fh:
            self.assertEqual(fh.read(), "A=1\n")
        self.assertEqual([f for f in os.listdir(self.root) if ".tmp-" in f], [])


class TargetTests(PosterTestCase):
    def test_profiles_and_order(self):
        ids = [t.id for t in config.targets_for("kotleta", None)]
        self.assertEqual(ids, ["fb:kotleta", "ig:kotleta", "linkedin", "x"])
        self.assertEqual(sorted(config.PROFILES), ["kotleta"])
        ids = [t.id for t in config.targets_for(None, "x,fb:demo,linkedin,ig:demo")]
        self.assertEqual(ids, ["fb:demo", "ig:demo", "linkedin", "x"])

    def test_bad_target_and_profile(self):
        for spec in ("tw", "fb:", "fb:Kotleta", "ig:a-b"):
            with self.assertRaises(config.ConfigError):
                config.targets_for(None, spec)
        with self.assertRaises(config.ConfigError):
            config.targets_for("nobody", None)
        with self.assertRaises(config.ConfigError):
            config.targets_for(None, None)

    def test_derivation_from_names_and_missing_messages(self):
        env = config.load_env(self.env_path)
        ids = {t.id for t in config.derived_targets(env)}
        self.assertTrue({"fb:demo", "fb:kotleta", "ig:kotleta", "x", "linkedin"} <= ids)
        self.assertNotIn("ig:demo", ids)
        t = config.parse_target("ig:demo")
        self.assertEqual(t.missing(env), ["IG_DEMO_USER_ID"])
        # a target outside every profile is derived from its variable name alone
        self.assertIn("ig:demo", {t.id for t in config.derived_targets({**env, "IG_DEMO_USER_ID": "1"})})
        env.pop("X_ACCESS_SECRET")
        self.assertEqual(config.parse_target("x").missing(env), ["X_ACCESS_SECRET"])

    def test_settings_defaults_and_overrides(self):
        s = config.load_settings({})
        self.assertEqual((s.graph_version, s.linkedin_version, str(s.cap)), ("v27.0", "202610", "5.00"))
        s = config.load_settings({"X_MONTHLY_CAP_USD": "7.5", "X_PRICE_POST": "0.02"})
        self.assertEqual((str(s.cap), str(s.price_post)), ("7.5", "0.02"))
        for bad in ("abc", "-1", "NaN", "Infinity", "1e"):
            with self.assertRaises(config.ConfigError):
                config.load_settings({"X_MONTHLY_CAP_USD": bad})
        with self.assertRaises(config.ConfigError):
            config.load_settings({"META_GRAPH_VERSION": "27"})
