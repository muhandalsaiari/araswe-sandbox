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


if __name__ == "__main__":
    unittest.main()
