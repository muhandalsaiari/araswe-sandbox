#!/usr/bin/env python3
"""anchor: model-free, language-agnostic code localization from an issue text.

Reads an issue (any natural language), pulls out only the parts that stay in
English whatever language the issue is written in -- traceback frames, file
paths, code spans, dotted names, CamelCase / snake_case identifiers, exception
names -- keeps the ones that exist in the repository, ranks them by how
specific they are, and resolves them to definitions (path:line).

No model call, no network, standard library only. Plain natural-language
words are never used, so an issue and its translation give the same output
as long as the code parts are kept verbatim.

Usage (inside the sandbox, repository at /workspace):
    python3 anchor.py --query "Router.__init__ on_startup fastapi/routing.py"
        (what run_skill_script sends for a dict argument with key query; the
        model copies only the code names from the issue, so no prose and no
        brackets reach the tool-call parser)
    python3 anchor.py "<full issue text>"
    python3 anchor.py --issue-file /tmp/issue.txt
    echo "<issue>" | python3 anchor.py
Options: --root DIR (default /workspace if present, else cwd), --k N anchors
(default 8), --files N ranked files (default 5).
"""
import math
import os
import re
import sys

A = re.ASCII

# Directories that never hold the code under repair (tests are also protected
# by the harness, so a fix there would be stripped anyway).
SKIP_DIRS = {
    ".git", "__pycache__", "tests", "test", "testing", "docs", "docs_src", "doc",
    "examples", "example", "benchmarks", "scripts", "venv", ".venv", "env",
    "build", "dist", "site-packages", "node_modules", ".tox", ".nox", ".eggs",
}

# Identifiers too generic to point anywhere.
STOP = {
    "self", "cls", "None", "True", "False", "str", "int", "float", "bool", "dict",
    "list", "tuple", "set", "bytes", "object", "type", "len", "print", "range",
    "open", "super", "isinstance", "issubclass", "getattr", "setattr", "hasattr",
    "kwargs", "args", "__init__", "__call__", "__name__", "__main__", "__file__",
    "main", "test", "tests", "value", "values", "name", "data", "key", "keys",
    "items", "return", "import", "from", "def", "class", "async", "await",
    "lambda", "yield", "pass", "raise", "except", "try", "finally", "with",
    "assert", "global", "nonlocal", "del", "elif", "else", "while", "for", "and",
    "not", "the", "pip", "python", "python3", "pytest", "http", "https", "www",
    "com", "org", "github", "json", "utf", "utf8", "foo", "bar", "baz",
    "result", "results", "error", "exception", "Exception",
    "ValueError", "TypeError", "KeyError", "AttributeError", "RuntimeError",
    "ImportError", "IndexError", "NameError", "OSError", "AssertionError",
    "NotImplementedError", "StopIteration", "DeprecationWarning", "UserWarning",
}
# Case-sensitive on purpose: `request` is generic, but `Request` is a real class in many repos.

# Priority of where a term was found (higher = more specific evidence).
P_TRACE, P_PATH, P_INLINE, P_DOTTED, P_BLOCK, P_PROSE = 6, 5, 4, 3, 2, 1
PRIO_WEIGHT = {P_TRACE: 3.0, P_PATH: 3.0, P_INLINE: 2.0, P_DOTTED: 1.5, P_BLOCK: 1.2, P_PROSE: 1.0}
PRIO_NAME = {P_TRACE: "traceback", P_PATH: "path", P_INLINE: "code span",
             P_DOTTED: "dotted name", P_BLOCK: "code block", P_PROSE: "identifier"}

URL_RE = re.compile(r"https?://\S+|www\.\S+", A)
TRACE_RE = re.compile(r'File "([^"\n]+)", line (\d+), in ([A-Za-z_<][A-Za-z0-9_<>]*)', A)
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
INLINE_RE = re.compile(r"`([^`\n]{1,160})`")
PYPATH_RE = re.compile(r"(?<![A-Za-z0-9_/.\-])((?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_]+\.py)\b", A)
DOTTED_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b", A)
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b", A)
DEF_RE = re.compile(r"^[ \t]*(?:async[ \t]+def|def|class)[ \t]+([A-Za-z_][A-Za-z0-9_]*)", A)
NOT_DOTTED_SUFFIX = (".py", ".txt", ".md", ".toml", ".cfg", ".ini", ".json", ".yaml",
                     ".yml", ".html", ".js", ".css", ".rst", ".lock")


def is_codey(tok):
    """True for tokens that look like code rather than an English word."""
    core = tok.strip("_")
    if not core:
        return False
    if tok.startswith("__") and tok.endswith("__"):
        return True
    if "_" in core:
        return True
    if re.search(r"[a-z][A-Z]", tok) or re.search(r"[A-Z]{2,}[a-z]", tok):
        return True
    return bool(re.search(r"(Error|Exception|Warning)$", tok))


def _keep(tok):
    return len(tok) >= 3 and tok not in STOP and not tok.isdigit()


def extract_candidates(text):
    """Return (terms, paths, frames).

    terms:  dict term -> best priority found
    paths:  list of .py paths mentioned (normalised, forward slashes)
    frames: list of (path, line, func) from tracebacks, in order of appearance
    Only ASCII code-like tokens are considered, so prose in any language is ignored.
    """
    terms, paths, frames = {}, [], []

    def add(tok, prio):
        if _keep(tok) and prio > terms.get(tok, 0):
            terms[tok] = prio

    text = URL_RE.sub(" ", text)

    for path, line, func in TRACE_RE.findall(text):
        frames.append((path.replace("\\", "/"), int(line), func))
        if func != "<module>":
            add(func, P_TRACE)

    blocks = FENCE_RE.findall(text)
    prose = FENCE_RE.sub(" ", text)
    # Names the reporter defines in their own example code are theirs, not the library's.
    own = set(re.findall(r"^[ \t]*(?:async[ \t]+def|def|class)[ \t]+([A-Za-z_][A-Za-z0-9_]*)", "\n".join(blocks), re.M | A))
    for block in blocks:
        for d in DOTTED_RE.findall(block):
            last = d.split(".")[-1]
            if not d.endswith(NOT_DOTTED_SUFFIX) and (len(last) >= 4 or is_codey(last)):
                add(last, P_BLOCK)
        for tok in IDENT_RE.findall(block):
            if is_codey(tok):
                add(tok, P_BLOCK)

    for span in INLINE_RE.findall(prose):
        toks = IDENT_RE.findall(span)
        for d in DOTTED_RE.findall(span):
            if not d.endswith(NOT_DOTTED_SUFFIX):
                for part in d.split("."):
                    add(part, P_INLINE)  # every part of an explicitly marked dotted name
        if len(toks) == 1:
            add(toks[0], P_INLINE)  # the author marked this exact word as code
        else:
            for tok in toks:
                after = span[span.find(tok) + len(tok):].lstrip()
                if is_codey(tok) or after.startswith(("(", "=")) or tok[:1].isupper():
                    add(tok, P_INLINE)

    for p in PYPATH_RE.findall(text):
        paths.append(p.replace("\\", "/").lstrip("./"))

    prose_no_code = INLINE_RE.sub(" ", prose)
    for d in DOTTED_RE.findall(prose_no_code):
        parts = d.split(".")
        if d.endswith(NOT_DOTTED_SUFFIX) or len(parts[0]) < 2 or any(len(p) == 1 for p in parts):
            continue  # e.g. "e.g", "v1.2", "index.html"
        if any(is_codey(p) for p in parts) or len(parts) >= 3:
            add(parts[-1], P_DOTTED)
    for tok in IDENT_RE.findall(prose_no_code):
        if is_codey(tok):
            add(tok, P_PROSE)

    for name in own:
        if terms.get(name, 0) <= P_BLOCK:
            terms.pop(name, None)  # keep it only if the prose also points at it explicitly

    return terms, list(dict.fromkeys(paths)), frames


def extract_modules(text):
    """Dotted module paths (pkg.sub.mod or pkg.mod.Name) as candidate files: pkg/sub/mod.py, pkg/mod.py."""
    text = URL_RE.sub(" ", text)
    out = []
    for d in DOTTED_RE.findall(text):
        parts = d.split(".")
        if len(parts) < 2 or d.endswith(NOT_DOTTED_SUFFIX) or parts[0] in ("self", "cls"):
            continue
        if any(len(p) < 2 for p in parts):
            continue
        for cut in (len(parts), len(parts) - 1):
            if cut >= 2:
                out.append("/".join(parts[:cut]) + ".py")
    return list(dict.fromkeys(out))


def load_repo(root, skip_dirs=SKIP_DIRS):
    """Read every .py file under root (skipping test/doc folders). Returns rel_path -> text."""
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs and not d.startswith("."))
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            try:
                with open(full, encoding="utf-8", errors="ignore") as fh:
                    files[rel] = fh.read()
            except OSError:
                continue
    return files


class Index:
    """Identifier sets and definitions for a set of files."""

    def __init__(self, files):
        self.files = files
        self.tokens = {}
        self.defs = {}
        for rel, text in files.items():
            self.tokens[rel] = set(IDENT_RE.findall(text))
            for i, line in enumerate(text.splitlines(), 1):
                m = DEF_RE.match(line)
                if m:
                    kind = "class" if line.lstrip().startswith("class") else "def"
                    self.defs.setdefault(m.group(1), []).append((rel, i, kind))
        self.n = len(files)

    def df(self, term):
        return sum(1 for toks in self.tokens.values() if term in toks)

    def first_use(self, rel, term):
        pat = re.compile(r"\b" + re.escape(term) + r"\b", A)
        for i, line in enumerate(self.files[rel].splitlines(), 1):
            if pat.search(line):
                return i
        return 1


def _path_match(rel, mentioned):
    """True if a repo file and a mentioned/traceback path refer to the same file."""
    m = mentioned.lower().replace("\\", "/")
    r = rel.lower()
    return m == r or m.endswith("/" + r) or r.endswith("/" + m) or (("/" not in m) and r.split("/")[-1] == m)


def analyze(text, files=None, root=None, index=None):
    """Rank files and anchors for an issue.

    Returns dict with keys: files (list of (score, rel)), anchors (list of str),
    terms (list of (term, prio, df)), blind (bool: no usable code evidence).
    """
    if index is None:
        index = Index(files if files is not None else load_repo(root))
    terms, paths, frames = extract_candidates(text)
    n = max(index.n, 1)
    big = math.log(n + 1)
    scores = dict((rel, 0.0) for rel in index.files)

    live = []
    for term, prio in terms.items():
        df = index.df(term)
        if df == 0:
            continue
        idf = math.log((n + 1) / (df + 0.5))
        w = PRIO_WEIGHT[prio] * idf
        live.append((w, term, prio, df))
        for rel, toks in index.tokens.items():
            if term in toks:
                scores[rel] += w
        for rel, _line, _kind in index.defs.get(term, []):
            scores[rel] += w  # defining the symbol counts double
        tl = term.lower()
        if len(tl) >= 4:
            for rel in index.files:
                if tl in rel.split("/")[-1].lower():
                    scores[rel] += 2 * w  # file named after the term

    path_hits = []
    for p in paths:
        for rel in index.files:
            if _path_match(rel, p):
                scores[rel] += PRIO_WEIGHT[P_PATH] * big
                path_hits.append(rel)

    module_hits = []
    for mod in extract_modules(text):
        for rel in index.files:
            rl, ml = rel.lower(), mod.lower()
            if (rl == ml or rl.endswith("/" + ml)) and rel not in path_hits and rel not in module_hits:
                scores[rel] += PRIO_WEIGHT[P_DOTTED] * big
                module_hits.append(rel)

    frame_hits = []
    for order, (fpath, line, func) in enumerate(frames):
        for rel in index.files:
            if _path_match(rel, fpath):
                scores[rel] += PRIO_WEIGHT[P_TRACE] * big * (1 + 0.15 * order)
                frame_hits.append((rel, line, func))

    ranked = sorted(((round(s, 2), rel) for rel, s in scores.items() if s > 0), key=lambda x: (-x[0], x[1]))
    rank_of = dict((rel, i) for i, (_s, rel) in enumerate(ranked))
    live.sort(key=lambda x: (-x[0], x[1]))

    anchors, seen = [], set()
    for rel, line, func in reversed(frame_hits):  # innermost frame first
        key = (rel, line)
        if key not in seen:
            seen.add(key)
            anchors.append("%s -> %s:%d (traceback frame)" % (func, rel, line))
    for rel in path_hits:
        if (rel, 0) not in seen:
            seen.add((rel, 0))
            anchors.append("%s -> %s:1 (file named in issue)" % (rel.split("/")[-1], rel))
    # Definitions first (they are where fixes usually go), then plain uses for terms never defined here.
    for w, term, prio, df in live:
        defs = sorted(index.defs.get(term, []), key=lambda d: rank_of.get(d[0], 10 ** 6))
        for rel, line, kind in defs[:2]:
            if (rel, line) not in seen:
                seen.add((rel, line))
                anchors.append("%s -> %s:%d (%s, from %s)" % (term, rel, line, kind, PRIO_NAME[prio]))
    for w, term, prio, df in live:
        if index.defs.get(term):
            continue
        users = sorted((rel for rel, toks in index.tokens.items() if term in toks),
                       key=lambda r: rank_of.get(r, 10 ** 6))
        if users:
            rel = users[0]
            line = index.first_use(rel, term)
            if (rel, line) not in seen:
                seen.add((rel, line))
                anchors.append("%s -> %s:%d (used here, from %s)" % (term, rel, line, PRIO_NAME[prio]))
    for rel in module_hits:
        if (rel, 0) not in seen:
            seen.add((rel, 0))
            anchors.append("%s -> %s:1 (module named in issue)" % (rel.split("/")[-1], rel))

    return {
        "files": ranked,
        "anchors": anchors,
        "terms": [(t, p, d) for _w, t, p, d in live],
        "blind": not (live or path_hits or frame_hits or module_hits),
    }


def format_report(result, k=8, nfiles=5):
    if result["blind"]:
        return ("NO_ANCHOR: the issue names no code identifier, file or traceback frame that exists in "
                "this repository. Use your normal search.")
    out = ["ANCHORS (most specific first; read the first one before anything else):"]
    for i, a in enumerate(result["anchors"][:k], 1):
        out.append("%d. %s" % (i, a))
    out.append("FILES (best match first):")
    for i, (s, rel) in enumerate(result["files"][:nfiles], 1):
        out.append("%d. %s  score %.1f" % (i, rel, s))
    return "\n".join(out)


QUERY_STRIP = "[](){}<>`'\",;:"


def query_to_text(query):
    """Turn a model-written list of code names into issue-like text.

    In query mode the model passes only the code parts it copied from the issue
    (names, dotted names, .py paths), separated by spaces. Each one is treated as
    if the issue had marked it as code, so plain-looking names such as Router
    count too. Brackets, quotes and backticks are stripped first.
    """
    out = []
    for tok in query.split():
        tok = tok.strip(QUERY_STRIP)
        if not tok:
            continue
        if tok.endswith(".py") or "/" in tok:
            out.append(tok)  # a path: matched against file names
        else:
            out.append("`%s`" % tok)  # a name: counts like a code span
    return "\n".join(out)


def main(argv):
    root, k, nfiles, issue_file, rest, query = None, 8, 5, None, [], None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]; i += 2
        elif a == "--k" and i + 1 < len(argv):
            k = int(argv[i + 1]); i += 2
        elif a == "--files" and i + 1 < len(argv):
            nfiles = int(argv[i + 1]); i += 2
        elif a == "--issue-file" and i + 1 < len(argv):
            issue_file = argv[i + 1]; i += 2
        elif a == "--query" and i + 1 < len(argv):
            query = argv[i + 1]; i += 2
        elif a.startswith("--"):
            i += 1  # unknown key from a dict argument: ignore the key, keep its value
        else:
            rest.append(a); i += 1
    if root is None:
        root = "/workspace" if os.path.isdir("/workspace") else os.getcwd()
    if issue_file is None and len(rest) == 1 and os.path.isfile(rest[0]):
        issue_file = rest[0]
    if query is not None:
        text = query_to_text(query)
    elif issue_file:
        with open(issue_file, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    elif rest:
        text = " ".join(rest)
    else:
        text = sys.stdin.read()
    if not text.strip():
        print("NO_ANCHOR: empty query. Pass the code names from the issue as the query.")
        return 0
    print(format_report(analyze(text, root=root), k=k, nfiles=nfiles))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
