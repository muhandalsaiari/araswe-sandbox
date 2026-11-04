"""Print an agent trace as one line per tool call: what was called, with what, and what came back.

usage: python3 -I tools/trace_calls.py <trace_json> [--width N]
Skill calls (run_skill_script, load_skill, ...) are printed in full (up to 1500 chars) since they are what we audit;
every other call is cut to --width chars (default 140). Per LLM step it also shows output tokens, so long thinking shows.
"""
import json
import sys

SKILL_TOOLS = {"run_skill_script", "load_skill", "load_skill_resource", "list_skills"}


def short(x, n):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + " …(%d chars)" % len(s)


def main(argv):
    path, width = argv[0], 140
    if "--width" in argv:
        width = int(argv[argv.index("--width") + 1])
    steps = json.load(open(path))["steps"]
    n = 0
    for s in steps:
        m = s.get("metrics") or {}
        obs = s.get("observation")
        res = (obs or {}).get("content", "") if isinstance(obs, dict) else ""
        for c in s.get("tool_calls") or []:
            n += 1
            name, args = c.get("function_name"), c.get("arguments") or {}
            lim = 1500 if name in SKILL_TOOLS else width
            print("%2d. [out %s tok] %s %s" % (n, m.get("completion_tokens", "?"), name, short(args, lim)))
            print("      -> " + short(res, lim))
        if not s.get("tool_calls") and m:
            print("    (step with no tool call, out %s tok) %s" % (m.get("completion_tokens", "?"), short(s.get("message") or "", 200)))
    print("TOTAL tool calls: %d" % n)


if __name__ == "__main__":
    main(sys.argv[1:])
