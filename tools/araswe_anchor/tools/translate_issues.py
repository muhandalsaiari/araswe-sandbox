#!/usr/bin/env python3
"""Translate task issues for Experiment A / the agent study, keeping code byte-identical.

Modes
  mix   every code part (code blocks, `code spans`, URLs, traceback lines, .py paths, dotted names,
        snake_case / CamelCase identifiers) is swapped for a placeholder [[C<n>]] before translation and
        put back after. A row is kept only if every placeholder comes back exactly once.
  free  no placeholders: the translator gets the plain issue and translates as it sees fit
        (shows what happens when nobody protects the code).

Translator: any OpenAI-compatible chat API (DeepSeek by default). The key is read from an env file
outside the repo (default ~/.config/araswe/deepseek.env, line DEEPSEEK_API_KEY=...). Standard library only.

Usage
  python3 -I translate_issues.py --list-models
  python3 -I translate_issues.py --model <id> --lang ar --mode mix --n 3
  python3 -I translate_issues.py --model <id> --lang ar --mode mix            (all tasks; resumes)
Output: <out>/<lang>_<mode>_tasks.jsonl (instance_id, repo, problem_statement + _meta), failures in
<out>/<lang>_<mode>_failed.jsonl. Prints token usage so cost can be read off the provider's price list.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "anchor" / "scripts"))
import anchor  # noqa: E402

LANGS = {"ar": "Arabic", "zh": "Simplified Chinese", "ru": "Russian", "es": "Spanish", "fr": "French",
         "de": "German", "ja": "Japanese", "ko": "Korean", "hi": "Hindi", "tr": "Turkish", "fa": "Persian",
         "pt": "Brazilian Portuguese", "vi": "Vietnamese", "id": "Indonesian"}

A = re.ASCII
# Masked in this order; each pattern only sees text the earlier ones left.
MASKS = [
    re.compile(r"```.*?(?:```|\Z)", re.S),                                  # fenced code block
    re.compile(r"`[^`\n]+`"),                                                # inline code span
    re.compile(r"https?://\S+|www\.\S+", A),                                 # URL
    re.compile(r'^[ \t]*File "[^"\n]+", line \d+.*(?:\n[ \t]+(?!File ")\S.*)?$', re.M | A),  # frame + its source line
    re.compile(r"^[ \t]*(?:Traceback \(most recent call last\):|[A-Za-z_.]*(?:Error|Exception|Warning)\b:?.*)$", re.M | A),
    re.compile(r"(?<![A-Za-z0-9_/.\-])(?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_\-]+\.(?:py|toml|cfg|ini|txt|json|ya?ml|md)\b", A),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+(?:\(\))?", A),  # dotted name
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\(\)", A),                          # call like foo()
]
IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b", A)
PH = "[[C%d]]"
PH_RE = re.compile(r"\[\[\s*C\s*([0-9٠-٩۰-۹]+)\s*\]\]")
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩"
                       "۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def mask(text):
    """Return (masked_text, parts) with every code part replaced by [[C<n>]]; parts[n] is the original."""
    parts = []

    def sub(m):
        parts.append(m.group(0))
        return PH % (len(parts) - 1)

    out = text
    for rx in MASKS:
        segs = re.split(r"(\[\[C\d+\]\])", out)  # never mask inside an existing placeholder
        out = "".join(s if s.startswith("[[C") else rx.sub(sub, s) for s in segs)
    segs = re.split(r"(\[\[C\d+\]\])", out)
    out = "".join(s if s.startswith("[[C") else IDENT.sub(lambda m: sub(m) if anchor.is_codey(m.group(0)) else m.group(0), s)
                  for s in segs)
    return out, parts


def restore(translated, parts):
    """Put the code parts back. Returns (text, problems); problems is empty when every placeholder came back once."""
    seen = {}
    for m in PH_RE.finditer(translated):
        i = int(m.group(1).translate(DIGITS))
        seen[i] = seen.get(i, 0) + 1
    problems = []
    missing = [i for i in range(len(parts)) if seen.get(i, 0) == 0]
    dup = [i for i, c in seen.items() if c > 1]
    extra = [i for i in seen if i >= len(parts)]
    if missing:
        problems.append("missing placeholders %s" % missing[:10])
    if dup:
        problems.append("repeated placeholders %s" % dup[:10])
    if extra:
        problems.append("unknown placeholders %s" % extra[:10])

    def back(m):
        i = int(m.group(1).translate(DIGITS))
        return parts[i] if i < len(parts) else m.group(0)
    return PH_RE.sub(back, translated), problems


def code_terms(text):
    terms, paths, frames = anchor.extract_candidates(text)
    return set(terms), set(paths), set(frames)


SYSTEM_MIX = ("You translate GitHub issues from English into %s. The text contains placeholders such as [[C3]]. "
              "Each one stands for a piece of code that must not change. Copy every placeholder exactly as written, "
              "with Latin letters and digits, exactly once, where it belongs in the translated sentence. Translate "
              "everything else, including headings and list items, the way a native %s-speaking software developer "
              "would write it. Keep the Markdown structure and line breaks. Output only the translation.")
SYSTEM_FREE = ("Translate this GitHub issue from English into %s, the way a native %s-speaking software developer "
               "would write it. Keep the Markdown structure. Output only the translation.")


def load_env(path):
    env = {}
    p = Path(path).expanduser()
    if p.is_file():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(base, key, path, payload=None, timeout=600):
    req = urllib.request.Request(base.rstrip("/") + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def chat(base, key, model, system, user, max_tokens):
    payload = {"model": model, "temperature": 0, "max_tokens": max_tokens, "stream": False,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    last = None
    for attempt in range(4):
        try:
            r = api(base, key, "/chat/completions", payload)
            return r["choices"][0]["message"]["content"] or "", r.get("usage") or {}, r["choices"][0].get("finish_reason")
        except urllib.error.HTTPError as e:
            last = "HTTP %d %s" % (e.code, e.read()[:300].decode("utf-8", "ignore"))
            if e.code in (400, 401, 402, 403, 404):
                break  # bad request / auth / balance: retrying will not help
        except Exception as e:  # network, timeout
            last = repr(e)[:300]
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="~/araswe/data/tasks.jsonl")
    ap.add_argument("--out", default="~/araswe/translations")
    ap.add_argument("--lang", default="ar")
    ap.add_argument("--mode", choices=["mix", "free"], default="mix")
    ap.add_argument("--model", help="model id (see --list-models)")
    ap.add_argument("--base-url", default="https://api.deepseek.com")
    ap.add_argument("--env-file", default="~/.config/araswe/deepseek.env")
    ap.add_argument("--key-var", default="DEEPSEEK_API_KEY")
    ap.add_argument("--n", type=int, help="translate only the first N untranslated tasks")
    ap.add_argument("--only", help="comma-separated instance_ids")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="mask and restore without calling the API (checks the masking)")
    a = ap.parse_args()

    key = os.environ.get(a.key_var) or load_env(a.env_file).get(a.key_var)
    if not key and not a.dry_run:
        sys.exit("no %s in the environment or in %s" % (a.key_var, a.env_file))
    if a.list_models:
        for m in api(a.base_url, key, "/models").get("data", []):
            print(m.get("id"))
        return
    if not a.model and not a.dry_run:
        sys.exit("--model is required (run --list-models first)")

    lang_name = LANGS.get(a.lang, a.lang)
    rows = [json.loads(l) for l in open(Path(a.tasks).expanduser(), encoding="utf-8") if l.strip()]
    if a.only:
        keep = set(a.only.split(","))
        rows = [r for r in rows if r["instance_id"] in keep]
    out_dir = Path(a.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("%s_%s_tasks.jsonl" % (a.lang, a.mode))
    fail_path = out_dir / ("%s_%s_failed.jsonl" % (a.lang, a.mode))
    done = set()
    if out_path.exists():
        done = {json.loads(l)["instance_id"] for l in open(out_path, encoding="utf-8") if l.strip()}
    todo = [r for r in rows if r["instance_id"] not in done]
    if a.n:
        todo = todo[:a.n]
    print("tasks %d, already done %d, to translate now %d -> %s" % (len(rows), len(done), len(todo), out_path))

    lock = threading.Lock()
    tot = {"prompt_tokens": 0, "completion_tokens": 0, "prompt_cache_hit_tokens": 0, "ok": 0, "failed": 0, "terms_changed": 0}

    def one(r):
        src = r["problem_statement"]
        if a.mode == "mix":
            masked, parts = mask(src)
            system = SYSTEM_MIX % (lang_name, lang_name)
        else:
            masked, parts = src, []
            system = SYSTEM_FREE % (lang_name, lang_name)
        meta = {"lang": a.lang, "mode": a.mode, "model": a.model, "base_url": a.base_url, "n_placeholders": len(parts)}
        try:
            if a.dry_run:
                text, usage, finish = masked, {}, "dry_run"
            else:
                text, usage, finish = chat(a.base_url, key, a.model, system, masked, a.max_tokens)
            problems = []
            if finish not in ("stop", "dry_run"):
                problems.append("finish_reason=%s" % finish)
            if a.mode == "mix":
                text, more = restore(text, parts)
                problems += more
            if not text.strip():
                problems.append("empty translation")
            t0, t1 = code_terms(src), code_terms(text)
            meta.update(usage=usage, finish_reason=finish,
                        anchor_terms_same=t0 == t1,
                        anchor_terms_lost=sorted(t0[0] - t1[0])[:20], anchor_terms_new=sorted(t1[0] - t0[0])[:20])
            row = {"instance_id": r["instance_id"], "repo": r.get("repo"), "problem_statement": text, "_meta": meta}
            with lock:
                for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens"):
                    tot[k] += int(usage.get(k) or 0)
                if problems:
                    tot["failed"] += 1
                    row["_meta"]["problems"] = problems
                    with open(fail_path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print("FAIL %s: %s" % (r["instance_id"], "; ".join(problems)))
                else:
                    tot["ok"] += 1
                    tot["terms_changed"] += not meta["anchor_terms_same"]
                    with open(out_path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print("OK   %s  placeholders %d  tokens in/out %s/%s  anchor terms %s" % (
                        r["instance_id"], len(parts), usage.get("prompt_tokens", "-"), usage.get("completion_tokens", "-"),
                        "same" if meta["anchor_terms_same"] else "CHANGED lost=%s new=%s" % (
                            meta["anchor_terms_lost"][:5], meta["anchor_terms_new"][:5])))
        except Exception as e:
            with lock:
                tot["failed"] += 1
                print("FAIL %s: %s" % (r["instance_id"], e))

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        list(ex.map(one, todo))
    print("DONE ok=%d failed=%d anchor_terms_changed=%d  tokens: prompt %d (cache hit %d), completion %d" % (
        tot["ok"], tot["failed"], tot["terms_changed"], tot["prompt_tokens"], tot["prompt_cache_hit_tokens"],
        tot["completion_tokens"]))


if __name__ == "__main__":
    main()
