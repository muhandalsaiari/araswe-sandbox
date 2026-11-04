"""Unit tests for the forgiving edit skill. Run: python3 -m unittest discover -s tools/forgiving_edit/tests"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "edit", "scripts"))
import edit  # noqa: E402

SRC = '''def f(x):
    """Doc."""
    msg = f"bad {x!r}"

    return msg


def g():
    return 1


def h():
    return 1
'''


class EditTest(unittest.TestCase):
    def run_edit(self, old, new, src=SRC, name="m.py"):
        d = tempfile.mkdtemp()
        p = os.path.join(d, name)
        with open(p, "w") as fh:
            fh.write(src)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = edit.main(["--root", d, "--filepath", name, "--old_string", old, "--new_string", new])
        with open(p) as fh:
            return rc, buf.getvalue(), fh.read()

    def test_exact(self):
        rc, out, after = self.run_edit("    return msg", "    return msg.upper()")
        self.assertEqual(rc, 0)
        self.assertIn("return msg.upper()", after)
        self.assertNotIn("matched after fixing", out)

    def test_escaped_quotes(self):
        rc, out, after = self.run_edit('    msg = f\\"bad {x!r}\\"', '    msg = f\\"worse {x!r}\\"')
        self.assertEqual(rc, 0, out)
        self.assertIn('msg = f"worse {x!r}"', after)
        self.assertIn("quotes", out)

    def test_docstring_backslash_newline(self):
        # the leak seen on Kaggle 12B: \"\"\"Doc.\"\"\" then a backslash before the line break
        rc, out, after = self.run_edit('def f(x):\\\n    \\"\\"\\"Doc.\\"\\"\\"', 'def f(x):\n    """Better."""')
        self.assertEqual(rc, 0, out)
        self.assertIn('"""Better."""', after)

    def test_literal_backslash_n(self):
        rc, out, after = self.run_edit("def g():\\n    return 1\\n\\n\\ndef h", "def g():\\n    return 2\\n\\n\\ndef h")
        self.assertEqual(rc, 0, out)
        self.assertIn("def g():\n    return 2", after)
        self.assertIn("def h():\n    return 1", after)

    def test_blank_lines_ignored(self):
        rc, out, after = self.run_edit('    msg = f"bad {x!r}"\n    return msg', '    return f"bad {x!r}"')
        self.assertEqual(rc, 0, out)
        self.assertIn("blank_lines", out)
        self.assertIn('    """Doc."""\n    return f"bad {x!r}"\n', after)

    def test_ambiguous_refused(self):
        rc, out, after = self.run_edit("    return 1", "    return 3")
        self.assertEqual(rc, 1)
        self.assertIn("matches 2 places", out)
        self.assertEqual(after, SRC)

    def test_not_found_shows_closest_block(self):
        rc, out, after = self.run_edit("def g():\n    return 7", "def g():\n    return 8")
        self.assertEqual(rc, 1)
        self.assertEqual(after, SRC)
        self.assertIn("|     return 1", out)
        self.assertIn("def g():", out)

    def test_syntax_guard(self):
        # literal \n inside a real string in new_string becomes a real line break -> broken code, refused
        rc, out, after = self.run_edit("def g():\\n    return 1\\n\\n\\ndef h", 'def g():\\n    return "a\\nb"\\n\\n\\ndef h')
        self.assertEqual(rc, 1)
        self.assertIn("break Python syntax", out)
        self.assertEqual(after, SRC)

    def test_missing_args(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = edit.main(["--filepath", "x.py"])
        self.assertEqual(rc, 2)
        self.assertIn("needs filepath, old_string and new_string", buf.getvalue())

    def test_gap_never_applied(self):
        self.assertEqual(edit.line_runs("def g():\ndef h():", SRC), [])
        self.assertEqual(len(edit.line_runs("def g():\ndef h():", SRC, gap=3)), 1)

    def adk_wrapper(self, repo, script_args):
        """Run edit.py the way google/adk/tools/skill_toolset.py _build_wrapper_code does: files written
        to a temp folder, chdir there, sys.argv built from a dict via repr, runpy, non-zero SystemExit
        re-raised. Run in a child python so chdir and argv do not leak into this process."""
        import subprocess
        src = open(os.path.join(HERE, "..", "skills", "edit", "scripts", "edit.py")).read()
        argv = ["scripts/edit.py"]
        for k, v in script_args.items():
            argv.extend(["--%s" % k, str(v)])
        code = "\n".join([
            "import os, sys, tempfile, runpy",
            "_files = %r" % {"scripts/edit.py": src},
            "def _run():",
            "  o = os.getcwd()",
            "  with tempfile.TemporaryDirectory() as td:",
            "    for rel, c in _files.items():",
            "      fp = os.path.join(td, rel); os.makedirs(os.path.dirname(fp), exist_ok=True)",
            "      open(fp, 'w').write(c)",
            "    os.chdir(td)",
            "    try:",
            "      sys.argv = %r" % argv,
            "      try:",
            "        runpy.run_path('scripts/edit.py', run_name='__main__')",
            "      except SystemExit as e:",
            "        if e.code is not None and e.code != 0:",
            "          raise e",
            "    finally:",
            "      os.chdir(o)",
            "_run()"])
        env = dict(os.environ, PWD=repo)
        return subprocess.run([sys.executable, "-I", "-c", code], cwd=repo, env=env, capture_output=True, text=True)

    def test_adk_wrapper_multiline_quotes(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "m.py"), "w") as fh:
            fh.write(SRC)
        r = self.adk_wrapper(d, {"filepath": "m.py", "old_string": 'def f(x):\n    """Doc."""\n    msg = f"bad {x!r}"',
                                 "new_string": 'def f(x):\n    """Doc."""\n    msg = f\'it\\\'s "bad" {x!r}\''})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("EDITED m.py at line 1", r.stdout)
        with open(os.path.join(d, "m.py")) as fh:
            self.assertIn("""    msg = f'it\\'s "bad" {x!r}'""", fh.read())

    def test_adk_wrapper_not_edited_is_not_an_error(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "m.py"), "w") as fh:
            fh.write(SRC)
        r = self.adk_wrapper(d, {"filepath": "m.py", "old_string": "def g():\n    return 7", "new_string": "x"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NOT EDITED", r.stdout)
        self.assertIn("|     return 1", r.stdout)


if __name__ == "__main__":
    unittest.main()
