"""Unit tests for the anchor skill. Run: python3 -m unittest discover -s tests -v"""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "anchor" / "scripts" / "anchor.py"
sys.path.insert(0, str(SCRIPT.parent))
import anchor  # noqa: E402

REPO = {
    "mypkg/__init__.py": "from .encoders import jsonable_encoder\n",
    "mypkg/encoders.py": (
        "import json\n\n\n"
        "def jsonable_encoder(obj, exclude_none=False):\n"
        "    if exclude_none:\n"
        "        return dict((k, v) for k, v in obj.items() if v is not None)\n"
        "    return obj\n"
    ),
    "mypkg/routing.py": (
        "from .encoders import jsonable_encoder\n\n\n"
        "class APIRoute:\n"
        "    def get_route_handler(self):\n"
        "        return jsonable_encoder\n\n\n"
        "def serialize_response(response_content):\n"
        "    return jsonable_encoder(response_content)\n"
    ),
    "mypkg/cookies.py": "def parse_cookie(header):\n    return header.split(';')\n",
    "mypkg/utils.py": "def helper():\n    return 1\n",
    "tests/test_encoders.py": "from mypkg.encoders import jsonable_encoder\n",
    "docs_src/tutorial.py": "jsonable_encoder = None\n",
}

ISSUE_EN = """When I call `jsonable_encoder` with `exclude_none=True` the result still contains None values.

```python
from mypkg.encoders import jsonable_encoder
jsonable_encoder(item, exclude_none=True)
```

Traceback (most recent call last):
  File "/usr/lib/python3.12/site-packages/mypkg/routing.py", line 10, in serialize_response
    return jsonable_encoder(response_content)
TypeError: something broke
"""

# Same issue, prose in Arabic, code kept verbatim (the "mixed" style of the resource).
ISSUE_AR = """عند استدعاء `jsonable_encoder` مع `exclude_none=True` ما زالت النتيجة تحتوي على قيم None.

```python
from mypkg.encoders import jsonable_encoder
jsonable_encoder(item, exclude_none=True)
```

Traceback (most recent call last):
  File "/usr/lib/python3.12/site-packages/mypkg/routing.py", line 10, in serialize_response
    return jsonable_encoder(response_content)
TypeError: something broke
"""


class AnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        for rel, text in REPO.items():
            p = cls.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_extracts_code_parts(self):
        terms, paths, frames = anchor.extract_candidates(ISSUE_EN)
        self.assertIn("jsonable_encoder", terms)
        self.assertIn("exclude_none", terms)
        self.assertIn("serialize_response", terms)
        self.assertEqual(terms["serialize_response"], anchor.P_TRACE)
        self.assertEqual(frames[0][1], 10)

    def test_ignores_plain_words(self):
        terms, _, _ = anchor.extract_candidates("The cookie parser breaks when the header has spaces.")
        self.assertEqual(terms, {})

    def test_language_invariant(self):
        en = anchor.extract_candidates(ISSUE_EN)
        ar = anchor.extract_candidates(ISSUE_AR)
        self.assertEqual(en, ar)
        r_en = anchor.analyze(ISSUE_EN, root=str(self.root))
        r_ar = anchor.analyze(ISSUE_AR, root=str(self.root))
        self.assertEqual(r_en["files"], r_ar["files"])
        self.assertEqual(r_en["anchors"], r_ar["anchors"])

    def test_ranks_definition_and_frame_first(self):
        r = anchor.analyze(ISSUE_EN, root=str(self.root))
        top2 = [p for _s, p in r["files"][:2]]
        self.assertIn("mypkg/encoders.py", top2)
        self.assertIn("mypkg/routing.py", top2)
        self.assertTrue(r["anchors"][0].startswith("serialize_response -> mypkg/routing.py:"))
        self.assertTrue(any(a.startswith("jsonable_encoder -> mypkg/encoders.py:4 (def") for a in r["anchors"]))

    def test_skips_tests_and_docs(self):
        r = anchor.analyze(ISSUE_EN, root=str(self.root))
        for _s, p in r["files"]:
            self.assertFalse(p.startswith(("tests/", "docs_src/")), p)

    def test_no_anchor(self):
        r = anchor.analyze("Das Login ist langsam, bitte beheben.", root=str(self.root))
        self.assertTrue(r["blind"])
        self.assertTrue(anchor.format_report(r).startswith("NO_ANCHOR"))

    def test_unknown_identifiers_dropped(self):
        r = anchor.analyze("Calling `totally_missing_function` fails.", root=str(self.root))
        self.assertTrue(r["blind"])

    def test_capitalised_class_not_stopped(self):
        terms, _, _ = anchor.extract_candidates("`Request` objects lose headers; `request` is generic.")
        self.assertIn("Request", terms)

    def test_cli_and_runtime(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(ISSUE_AR)
        try:
            t = time.time()
            out = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "--issue-file", fh.name],
                                 capture_output=True, text=True, check=True).stdout
            self.assertLess(time.time() - t, 2.0)
            self.assertIn("ANCHORS", out)
            self.assertIn("mypkg/encoders.py", out)
            out2 = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), ISSUE_EN],
                                  capture_output=True, text=True, check=True).stdout
            self.assertEqual(out, out2)
        finally:
            os.unlink(fh.name)

    def test_query_mode_cli(self):
        # What run_skill_script sends for a dict argument with key query.
        out = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--root", str(self.root),
             "--query", "[`APIRoute`, jsonable_encoder(), mypkg/routing.py]"],
            capture_output=True, text=True, timeout=30).stdout
        self.assertIn("APIRoute -> mypkg/routing.py:4", out)
        self.assertIn("jsonable_encoder -> mypkg/encoders.py:4", out)
        self.assertNotIn("NO_ANCHOR", out)

    def test_query_plain_name_counts(self):
        # A capitalised name with no underscore is dropped from prose but kept in a query.
        res = anchor.analyze(anchor.query_to_text("APIRoute"), root=str(self.root))
        self.assertEqual(res["files"][0][1], "mypkg/routing.py")

    def test_query_unknown_names(self):
        res = anchor.analyze(anchor.query_to_text("NoSuchThing other_missing"), root=str(self.root))
        self.assertTrue(res["blind"])

    def test_skill_md_is_brace_free(self):
        text = (SCRIPT.parent.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("{", text)
        self.assertNotIn("}", text)
        self.assertTrue(text.startswith("---\nname: anchor\n"))

    def test_output_is_brace_free(self):
        out = anchor.format_report(anchor.analyze(ISSUE_EN, root=str(self.root)))
        self.assertNotIn("{", out)
        self.assertNotIn("}", out)


class EvalSmokeTest(unittest.TestCase):
    """Runs the Experiment A tool end to end on a tiny fake dataset."""

    def test_eval_runs(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import eval_localization as ev
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "src"
            for rel, text in REPO.items():
                p = src / "fastapi" / rel.replace("mypkg/", "") if rel.startswith("mypkg/") else None
                if p:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(text.replace("mypkg", "fastapi"), encoding="utf-8")
            data = tmp / "data"
            (data / "snapshots").mkdir(parents=True)
            with tarfile.open(data / "snapshots" / "fastapi_1.tgz", "w:gz") as tf:
                tf.add(src / "fastapi", arcname="fastapi")
            task = {"instance_id": "fastapi_1", "repo": "fastapi/fastapi",
                    "problem_statement": ISSUE_EN.replace("mypkg", "fastapi"),
                    "patch": "--- a/fastapi/encoders.py\n+++ b/fastapi/encoders.py\n@@ -1 +1 @@\n-x\n+y\n"}
            (data / "tasks.jsonl").write_text(json.dumps(task) + "\n", encoding="utf-8")
            args = type("A", (), dict(data=str(data), cache=str(tmp / "cache"), variant=None, label="en",
                                      out=str(tmp / "out"), only=None, reproduce=False, verbose=False))()
            summ = ev.run(args)
            self.assertEqual(summ["anchor"][1], 1.0)  # top-3 hit
            self.assertTrue((tmp / "out" / "en_per_task.csv").exists())


if __name__ == "__main__":
    unittest.main()
