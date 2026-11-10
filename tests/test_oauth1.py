"""OAuth 1.0a signer against the worked example on X's documentation page
https://docs.x.com/fundamentals/authentication/oauth-1-0a/creating-a-signature
(read 2026-11-09). The values below are that page's published sample values, not credentials."""

import re
import urllib.parse

from poster import xapi
from tests.base import PosterTestCase

DOC = {
    "consumer_key": "xvz1evFS4wEEPTGEFPHBog",
    "consumer_secret": "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
    "token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
    "token_secret": "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
    "nonce": "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
    "timestamp": "1318622958",
    "url": "https://api.x.com/1.1/statuses/update.json?include_entities=true",
    "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
    "signature": "Ls93hJiZbQ3akF3HF3x1Bz8/zU4=",   # "OAuth signature" on the page
}


def fields(header):
    return dict((k, urllib.parse.unquote(v)) for k, v in re.findall(r'(\w+)="([^"]*)"', header))


class OAuth1Tests(PosterTestCase):
    def header(self, **kw):
        return xapi.oauth1_header("POST", DOC["url"], DOC["consumer_key"], DOC["consumer_secret"],
                                  DOC["token"], DOC["token_secret"], nonce=DOC["nonce"],
                                  timestamp=DOC["timestamp"], **kw)

    def test_signature_matches_the_documented_example(self):
        h = self.header(form={"status": DOC["status"]})
        self.assertEqual(fields(h)["oauth_signature"], DOC["signature"])

    def test_header_order_and_quoting(self):
        h = self.header(form={"status": DOC["status"]})
        self.assertTrue(h.startswith("OAuth "))
        names = re.findall(r'(\w+)="', h)
        self.assertEqual(names, ["oauth_consumer_key", "oauth_nonce", "oauth_signature",
                                 "oauth_signature_method", "oauth_timestamp", "oauth_token",
                                 "oauth_version"])
        self.assertIn('oauth_signature="Ls93hJiZbQ3akF3HF3x1Bz8%2FzU4%3D"', h)
        self.assertIn('oauth_signature_method="HMAC-SHA1"', h)
        self.assertIn('oauth_version="1.0"', h)

    def test_json_and_multipart_bodies_are_not_signed(self):
        # The signer only ever sees method, URL and form params: a JSON/multipart request is
        # signed exactly like a body-less request to the same URL.
        url = "https://api.x.com/2/tweets"
        a = xapi.oauth1_header("POST", url, "k", "s", "t", "ts", nonce="n", timestamp="1")
        b = xapi.oauth1_header("POST", url, "k", "s", "t", "ts", nonce="n", timestamp="1", form={})
        c = xapi.oauth1_header("POST", url, "k", "s", "t", "ts", nonce="n", timestamp="1",
                               form={"text": "x"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_nonce_is_word_characters_only(self):
        for _ in range(20):
            n = xapi.make_nonce()
            self.assertRegex(n, r"^\w{30,}$")
