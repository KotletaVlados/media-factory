"""Vendor claims here are documented shapes; all replies below are synthetic fixtures."""
import base64
import json
from factory.authoring import gemini, prompts, budget
from factory.authoring.common import Refusal
from tests.base import PosterTestCase, FakeTransport, CANARIES
from tests import panel_fixture as pf


class GeminiTest(PosterTestCase):
    def test_all_request_shapes_and_key_only_in_header(self):
        for op in prompts.OUTPUT:
            prompt = prompts.build(op, pf.AUTHOR_PROFILE, {"topic": "Test topic", "variants": {"x": {"text": "current text"}}}, "x", "shorter")
            request = gemini.request(op, CANARIES["GEMINI_API_KEY"], prompt, b"bytes", "audio/ogg" if op == "voice" else "image/jpeg")
            fake = FakeTransport([pf.gemini_reply({"topics": pf.TOPICS})])
            fake.send(request)
            body = json.loads(fake.requests[0].body)
            self.assertFalse(body["store"])
            self.assertEqual(request.timeout, 120)
            self.assertEqual(body["generation_config"]["max_output_tokens"], prompts.OUTPUT[op])
            self.assertEqual(body["model"], budget.model(op))
            self.assertEqual(body["generation_config"]["thinking_level"], "minimal" if op == "voice" else "low")
            self.assertEqual(request.headers["Api-Revision"], "2026-05-20")
            self.assertNotIn(CANARIES["GEMINI_API_KEY"], request.url)
            self.assertNotIn(CANARIES["GEMINI_API_KEY"].encode(), request.body)
            self.assertEqual(body["input"][1]["data"], base64.b64encode(b"bytes").decode())
            if op != "voice":
                self.assertEqual(body["response_format"]["schema"], prompts.SCHEMAS[op])
                self.assertEqual(body["input"][1]["resolution"], "high")
                from factory.authoring import profile
                for name, *_ in profile.FIELDS:
                    self.assertIn(profile.value(pf.AUTHOR_PROFILE, name), prompt)
            if op == "regenerate":
                self.assertIn("current text", prompt)
                self.assertIn("shorter", prompt)

    def test_steps_last_output_and_output_text(self):
        for path in ("steps", "output_text"):
            value, used = gemini.parse("expand", pf.gemini_reply(pf.TEXTS, path=path).json())
            self.assertEqual(value, pf.TEXTS)
            self.assertEqual(path, used)
        data = pf.gemini_reply({"text": "last"}).json()
        data["steps"].insert(0, {"type": "model_output", "content": [{"type": "text", "text": "wrong"}]})
        self.assertEqual(gemini.parse("regenerate", data)[0], {"text": "last"})
        self.assertEqual(gemini.parse("voice", pf.gemini_reply("слова").json())[0], "слова")

    def test_incomplete_failed_empty_bad_json_and_wrong_shapes(self):
        for status, message in (("incomplete", gemini.INCOMPLETE), ("failed", gemini.INVALID),
                                ("cancelled", gemini.INVALID), ("requires_action", gemini.INVALID)):
            with self.assertRaisesRegex(Refusal, message):
                gemini.parse("expand", pf.gemini_reply(pf.TEXTS, status=status).json())
        cases = [("expand", ""), ("expand", "not JSON"), ("expand", []),
                 ("expand", {"x": "only one"}), ("expand", dict(pf.TEXTS, extra="no")),
                 ("topics", {"topics": pf.TOPICS[:2]}), ("topics", {"topics": [dict(pf.TOPICS[0], title="")] * 3}),
                 ("regenerate", {"text": "x" * 5001})]
        for op, value in cases:
            with self.subTest(op=op, type=type(value).__name__), self.assertRaisesRegex(Refusal, gemini.INVALID):
                gemini.parse(op, pf.gemini_reply(value).json())
        for data in (None, [], {"status": "completed", "steps": [None]}, {"status": "completed", "output_text": 5}):
            with self.assertRaises(Refusal): gemini.parse("expand", data)

    def test_usage_rejects_unpriceable_shapes(self):
        self.assertEqual(gemini.usage(pf.gemini_reply("ok").json())["in"], 2000)
        for n in (None, -1, True, "1", 2**20000):
            self.assertIsNone(gemini.usage({"usage": {"total_input_tokens": n, "total_output_tokens": 1}}))


    def test_usage_total_disambiguates_thought_inclusion(self):
        self.assertEqual(gemini.billed_output({"in": 10, "out": 20, "thought": 5, "total": 30}), 20)
        self.assertEqual(gemini.billed_output({"in": 10, "out": 20, "thought": 5, "total": 35}), 25)
        self.assertEqual(gemini.billed_output({"in": 10, "out": 20, "thought": 5}), 25)
