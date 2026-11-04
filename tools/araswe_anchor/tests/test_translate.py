"""Tests for the masking used by tools/translate_issues.py (no network)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import translate_issues as T  # noqa: E402

ISSUE = """### Bug

When I call `jsonable_encoder` with exclude_none the result keeps None, see fastapi/encoders.py and
APIRoute.get_route_handler(). Docs: https://fastapi.tiangolo.com/tutorial/ .

```python
from fastapi.encoders import jsonable_encoder
jsonable_encoder(item, exclude_none=True)
```

Traceback (most recent call last):
  File "/x/fastapi/routing.py", line 10, in serialize_response
    return jsonable_encoder(response_content)
TypeError: something broke
"""

AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def fake_translate(masked, arabic_digits=False):
    """Replace every Latin word outside placeholders with an Arabic word; keep placeholders."""
    segs = re.split(r"(\[\[C\d+\]\])", masked)
    out = []
    for s in segs:
        if s.startswith("[[C"):
            out.append(s.translate(AR_DIGITS).replace("[[C", "[[ C") if arabic_digits else s)
        else:
            out.append(re.sub(r"[A-Za-z]+", "كلمة", s))
    return "".join(out)


class MaskTests(unittest.TestCase):
    def test_round_trip_identity(self):
        masked, parts = T.mask(ISSUE)
        text, problems = T.restore(masked, parts)
        self.assertEqual(text, ISSUE)
        self.assertEqual(problems, [])

    def test_code_survives_translation(self):
        masked, parts = T.mask(ISSUE)
        for ar in (False, True):
            text, problems = T.restore(fake_translate(masked, ar), parts)
            self.assertEqual(problems, [])
            for code in ("`jsonable_encoder`", "fastapi/encoders.py", "APIRoute.get_route_handler()",
                         "https://fastapi.tiangolo.com/tutorial/", "exclude_none",
                         'File "/x/fastapi/routing.py", line 10, in serialize_response', "TypeError: something broke",
                         "jsonable_encoder(item, exclude_none=True)"):
                self.assertIn(code, text)
            self.assertNotIn("Bug", text)  # prose really was replaced
            self.assertEqual(T.code_terms(text), T.code_terms(ISSUE))

    def test_dropped_placeholder_is_caught(self):
        masked, parts = T.mask(ISSUE)
        broken = masked.replace("[[C1]]", "", 1)
        _text, problems = T.restore(broken, parts)
        self.assertTrue(any("missing" in p for p in problems))

    def test_repeated_placeholder_is_caught(self):
        masked, parts = T.mask(ISSUE)
        _text, problems = T.restore(masked + " [[C0]]", parts)
        self.assertTrue(any("repeated" in p for p in problems))

    def test_prompts_have_no_braces_left(self):
        self.assertNotIn("%", T.SYSTEM_MIX % ("Arabic", "Arabic"))


class RepairTest(unittest.TestCase):
    """A translator that drops a placeholder first and fixes it when told."""

    def test_repair_turn(self):
        import json, os, tempfile
        calls = []

        def fake_chat(base, key, model, system, user, max_tokens, thinking=False, history=()):
            calls.append(list(history))
            out = fake_translate(user)
            if not history:
                out = out.replace("[[C1]]", "", 1)
            return out, {"prompt_tokens": 10, "completion_tokens": 5}, "stop"

        with tempfile.TemporaryDirectory() as d:
            tasks = os.path.join(d, "tasks.jsonl")
            with open(tasks, "w") as fh:
                fh.write(json.dumps({"instance_id": "x_1", "repo": "r", "problem_statement": ISSUE}) + "\n")
            orig, T.chat = T.chat, fake_chat
            argv = sys.argv
            try:
                sys.argv = ["t", "--tasks", tasks, "--out", d, "--model", "m", "--workers", "1"]
                os.environ["DEEPSEEK_API_KEY"] = "test"
                T.main()
            finally:
                T.chat, sys.argv = orig, argv
                os.environ.pop("DEEPSEEK_API_KEY", None)
            rows = [json.loads(l) for l in open(os.path.join(d, "ar_mix_tasks.jsonl"))]
        self.assertEqual(len(calls), 2)
        self.assertIn("missing placeholders [1]", calls[1][0][1])
        self.assertEqual(rows[0]["_meta"]["attempts"], 2)
        self.assertEqual(rows[0]["_meta"]["usage"]["prompt_tokens"], 20)
        self.assertIn("`jsonable_encoder`", rows[0]["problem_statement"])


if __name__ == "__main__":
    unittest.main()
