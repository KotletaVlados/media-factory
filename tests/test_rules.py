import os

from poster import rules
from tests.base import (PosterTestCase, make_bmp, make_gif, make_jpeg, make_png, make_tiff,
                        make_webp)


class XCountTests(PosterTestCase):
    def test_ascii_280_passes_281_refused_with_count(self):
        self.assertEqual(rules.check_text("x", "a" * 280).errors, [])
        errors = rules.check_text("x", "a" * 281).errors
        self.assertEqual(len(errors), 1)
        self.assertIn("281 weighted characters, X allows 280", errors[0])

    def test_weights(self):
        self.assertEqual(rules.x_weighted_length("Привіт, світ"), 12)       # Cyrillic weight 1
        self.assertEqual(rules.x_weighted_length("日本語"), 6)                 # CJK weight 2
        self.assertEqual(rules.x_weighted_length("😀"), 2)
        self.assertEqual(rules.x_weighted_length("© ®"), 5)                   # emoji 2 each
        self.assertEqual(rules.x_weighted_length("a’b"), 3)              # U+2019 in 8208-8223
        family = "👨‍👩‍👧"
        self.assertGreaterEqual(rules.x_weighted_length(family), 2)           # never under X's 2

    def test_urls(self):
        self.assertEqual(rules.x_weighted_length("https://example.com/" + "p" * 100), 23)
        self.assertEqual(rules.x_weighted_length("see https://a.co."), 4 + 23 + 1)
        self.assertEqual(rules.x_weighted_length("(http://a.co)"), 1 + 23 + 1)
        self.assertEqual(rules.x_weighted_length("go example.com now"), 3 + 23 + 4)
        long_domain = "a" * 30 + ".com"
        self.assertEqual(rules.x_weighted_length(long_domain), 34)          # max(23, own)
        self.assertTrue(rules.x_has_url("visit example.org"))
        self.assertFalse(rules.x_has_url("plain text, e.g. this"))

    def test_cashtags(self):
        self.assertEqual(rules.check_text("x", "$BTC up").errors, [])
        errors = rules.check_text("x", "$BTC and $ETH").errors
        self.assertIn("2 cashtags", errors[0])
        self.assertEqual(rules.count_cashtags("costs $5 or US$10"), 0)

    def test_nfc_before_counting(self):
        self.assertEqual(rules.x_weighted_length("é"), 1)


class InstagramTests(PosterTestCase):
    def test_caption_limits(self):
        self.assertEqual(rules.check_text("instagram", "a" * 2200).errors, [])
        self.assertIn("2201 characters, Instagram allows 2200",
                      rules.check_text("instagram", "a" * 2201).errors[0])
        self.assertIn("2201", rules.check_text("instagram", "😀" * 1100 + "a").errors[0])  # UTF-16
        tags = " ".join(f"#t{i}" for i in range(31))
        self.assertIn("31 hashtags", rules.check_text("instagram", tags).errors[0])
        self.assertEqual(rules.check_text("instagram", " ".join(f"#t{i}" for i in range(30))).errors, [])
        mentions = " ".join(f"@u{i}" for i in range(21))
        self.assertIn("21 @mentions", rules.check_text("instagram", mentions).errors[0])
        self.assertEqual(rules.count_mentions("mail me a@b.com"), 0)

    def info(self, name, data):
        return rules.sniff(self.image(name, data))

    def test_image_rules(self):
        self.assertIn("Instagram needs an image", rules.check_image("instagram", None).errors[0])
        self.assertIn("accepts jpeg", rules.check_image("instagram", self.info("a.png", make_png(100, 100))).errors[0])
        self.assertEqual(rules.check_image("instagram", self.info("ok.jpg", make_jpeg(800, 1000))).errors, [])
        self.assertEqual(rules.check_image("instagram", self.info("w.jpg", make_jpeg(1910, 1000))).errors, [])
        self.assertIn("aspect ratio 0.790", rules.check_image("instagram", self.info("t.jpg", make_jpeg(790, 1000))).errors[0])
        self.assertIn("aspect ratio 1.920", rules.check_image("instagram", self.info("v.jpg", make_jpeg(1920, 1000))).errors[0])
        big = self.info("big.jpg", make_jpeg(100, 100, pad=8_000_001))
        self.assertIn("Instagram allows 8000000", rules.check_image("instagram", big).errors[0])


class OtherNetworkTests(PosterTestCase):
    def info(self, name, data):
        return rules.sniff(self.image(name, data))

    def test_linkedin_counts_escaped_text(self):
        self.assertEqual(rules.check_text("linkedin", "a" * 3000).errors, [])
        errors = rules.check_text("linkedin", "a" * 2999 + "*").errors     # "*" -> "\*"
        self.assertIn("3001 characters after escaping", errors[0])
        pixels = self.info("huge.png", make_png(6016, 6016))                 # 36,192,256 px
        self.assertIn("fewer than 36152320", rules.check_image("linkedin", pixels).errors[0])
        self.assertEqual(rules.check_image("linkedin", self.info("ok.png", make_png(6000, 6000))).errors, [])
        self.assertIn("accepts", rules.check_image("linkedin", self.info("a.webp", make_webp(10, 10))).errors[0])

    def test_facebook(self):
        self.assertEqual(rules.check_text("facebook", "x" * 100_000).errors, [])
        big = self.info("big.jpg", make_jpeg(10, 10, pad=10_000_001))
        self.assertIn("Facebook allows 10000000", rules.check_image("facebook", big).errors[0])
        png = rules.check_image("facebook", self.info("p.png", make_png(10, 10, pad=1_000_001)))
        self.assertEqual(png.errors, [])
        self.assertIn("pixelated", png.warnings[0])
        for name, data in (("a.bmp", make_bmp()), ("a.tif", make_tiff()), ("a.gif", make_gif(5, 5))):
            self.assertEqual(rules.check_image("facebook", self.info(name, data)).errors, [], name)
        self.assertIn("accepts", rules.check_image("facebook", self.info("w.webp", make_webp(5, 5))).errors[0])

    def test_x_images(self):
        self.assertEqual(rules.check_image("x", self.info("s.gif", make_gif(5, 5, frames=1))).errors, [])
        self.assertIn("animated", rules.check_image("x", self.info("a.gif", make_gif(5, 5, frames=3))).errors[0])
        big = self.info("big.png", make_png(10, 10, pad=5_000_001))
        self.assertIn("X allows 5000000", rules.check_image("x", big).errors[0])
        self.assertEqual(rules.check_image("x", self.info("w.webp", make_webp(5, 5))).errors, [])
        self.assertIn("not a recognised image", rules.check_image("x", self.info("t.txt", b"hello")).errors[0])

    def test_sniffing_dimensions(self):
        cases = [("a.jpg", make_jpeg(1200, 800), "jpeg", (1200, 800)),
                 ("a.png", make_png(640, 480), "png", (640, 480)),
                 ("a.gif", make_gif(33, 44), "gif", (33, 44)),
                 ("x.webp", make_webp(1000, 700, "VP8X"), "webp", (1000, 700)),
                 ("l.webp", make_webp(321, 123, "VP8L"), "webp", (321, 123)),
                 ("y.webp", make_webp(500, 400, "VP8 "), "webp", (500, 400)),
                 ("b.bmp", make_bmp(), "bmp", (None, None)),
                 ("t.tif", make_tiff(), "tiff", (None, None))]
        for name, data, fmt, dims in cases:
            info = self.info(name, data)
            self.assertEqual((info.format, (info.width, info.height)), (fmt, dims), name)
            self.assertEqual(info.size, len(data))
        # format comes from magic bytes, not the file name
        self.assertEqual(self.info("lies.png", make_jpeg(5, 5)).format, "jpeg")

    def test_text_is_never_truncated_by_checks(self):
        text = "a" * 400
        c = rules.check_text("x", text)
        self.assertTrue(c.errors)
        self.assertEqual(text, "a" * 400)
