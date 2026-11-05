"""Translate-first arm of the agent study: the same 12B turns the issue into English in one extra call, before the agent runs.

usage: python3 -I tools/araswe_anchor/tools/translate_first.py <variant.jsonl> <out_tasks.jsonl> <ids_file> [--tasks ~/araswe/data/tasks.jsonl]

<variant.jsonl> holds the foreign issue text (translate_issues.py output). <out_tasks.jsonl> is a task file for the runner's
TASKS_JSONL with only the ids in <ids_file>, so a run can never pick up an untranslated task. Tokens of each call go to
<out_tasks.jsonl>.usage.jsonl and count toward that arm. Model server: MODEL_PORT (1235), SERVED_MODEL_NAME. Standard library only.
"""
import json
import os
import sys
import urllib.request

PROMPT = ("Translate this software issue into English. Keep all code, identifiers, file paths, tracebacks and URLs exactly as "
          "they are. Reply with the translation only.\n\n")


def ask(text):
    body = {"model": os.environ.get("SERVED_MODEL_NAME", "google/gemma-4-12b-qat"), "temperature": 0, "seed": 42, "max_tokens": 4096,
            "messages": [{"role": "user", "content": PROMPT + text}]}
    req = urllib.request.Request(f"http://localhost:{os.environ.get('MODEL_PORT', '1235')}/v1/chat/completions",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.load(r)
    c = j["choices"][0]
    return c["message"]["content"].strip(), j.get("usage", {}), c.get("finish_reason")


def main(argv):
    src, out, ids_file = argv[0], argv[1], argv[2]
    tasks = os.path.expanduser(argv[argv.index("--tasks") + 1] if "--tasks" in argv else "~/araswe/data/tasks.jsonl")
    ids = [x.strip() for x in open(ids_file) if x.strip()]
    tr = {}
    for line in open(os.path.expanduser(src)):
        r = json.loads(line)
        tr[r["instance_id"]] = r["problem_statement"]
    rows = {}
    for line in open(tasks):
        r = json.loads(line)
        rows[r["instance_id"]] = r
    with open(out, "w") as fo, open(out + ".usage.jsonl", "w") as fu:
        for i in ids:
            text, usage, finish = ask(tr[i])
            if finish != "stop" or not text:
                raise SystemExit(f"{i}: finish_reason {finish}, {len(text)} chars")
            fo.write(json.dumps({**rows[i], "problem_statement": text}, ensure_ascii=False) + "\n")
            fu.write(json.dumps({"instance_id": i, "usage": usage}) + "\n")
            print(i, usage, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
