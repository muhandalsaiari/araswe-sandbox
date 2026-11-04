"""Build a full task file whose issue text is a translation, for the agent runner's TASKS_JSONL.

usage: python3 -I tools/araswe_anchor/tools/make_variant_tasks.py <translations.jsonl> <out.jsonl> [--tasks ~/araswe/data/tasks.jsonl]

translate_issues.py writes only instance_id, repo, problem_statement and _meta. The runner needs the whole task
record (setup, tests, ...). This copies every row of the original tasks file and swaps in the translated
problem_statement. A task with no translation is an error, so a run can never mix languages silently.
"""
import json
import os
import sys


def main(argv):
    src, out = argv[0], argv[1]
    tasks = os.path.expanduser(argv[argv.index("--tasks") + 1] if "--tasks" in argv else "~/araswe/data/tasks.jsonl")
    tr = {}
    for line in open(os.path.expanduser(src)):
        r = json.loads(line)
        tr[r["instance_id"]] = r["problem_statement"]
    n = changed = 0
    missing = []
    rows = []
    for line in open(tasks):
        r = json.loads(line)
        n += 1
        if r["instance_id"] not in tr:
            missing.append(r["instance_id"])
            continue
        changed += r["problem_statement"] != tr[r["instance_id"]]
        r["problem_statement"] = tr[r["instance_id"]]
        rows.append(r)
    if missing:
        sys.exit("no translation for %d tasks, e.g. %s" % (len(missing), ", ".join(missing[:5])))
    with open(os.path.expanduser(out), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote %s: %d tasks, %d with new issue text" % (out, n, changed))


if __name__ == "__main__":
    main(sys.argv[1:])
