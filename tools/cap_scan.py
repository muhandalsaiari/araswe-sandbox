"""How often does the model ramble until it hits the output cap? Scans every run folder's traces.

usage: python3 -I tools/cap_scan.py [runs_dir=runs] [--min-runs N]
A turn is a cap hit when its completion tokens reach 98% of that run's max_output_tokens (read from the run's
settings.json; 8192 if absent). Per run folder and per model it prints: task-runs, LLM turns, cap-hit turns,
task-runs with at least one cap hit (all, and among unresolved ones), and the share of all output tokens spent in
cap-hit turns -- the clock a fix for rambling could give back. Reads only; writes nothing.
"""
import collections
import json
import sys
from pathlib import Path


def find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def main(argv):
    root = Path(argv[0] if argv and not argv[0].startswith("--") else "runs")
    min_runs = int(argv[argv.index("--min-runs") + 1]) if "--min-runs" in argv else 1
    per_model = collections.defaultdict(collections.Counter)
    print("%-34s %-30s %6s %7s %6s %9s %11s %8s" % ("run folder", "model", "runs", "turns", "caphit",
                                                    "runs_hit", "unres_hit", "tok_lost"))
    for d in sorted(p for p in root.iterdir() if (p / "traces").is_dir()):
        settings = {}
        if (d / "settings.json").exists():
            try:
                settings = json.load(open(d / "settings.json"))
            except Exception:
                pass
        cap = find_key(settings, "max_output_tokens") or 8192
        model = str(find_key(settings, "served_model_name") or find_key(settings, "model") or "?")[:30]
        resolved = {}
        if (d / "probe_results.jsonl").exists():
            for line in open(d / "probe_results.jsonl"):
                try:
                    r = json.loads(line)
                    resolved[r.get("id")] = bool(r.get("resolved"))
                except Exception:
                    pass
        c = collections.Counter()
        for t in sorted((d / "traces").glob("trace_*.json")):
            try:
                steps = json.load(open(t))["steps"]
            except Exception:
                continue
            tid = t.stem[len("trace_"):]
            toks = [(s.get("metrics") or {}).get("completion_tokens") or 0 for s in steps if s.get("metrics")]
            hits = [x for x in toks if x >= 0.98 * cap]
            c["runs"] += 1
            c["turns"] += len(toks)
            c["caphit"] += len(hits)
            c["runs_hit"] += bool(hits)
            c["out_tok"] += sum(toks)
            c["out_tok_hit"] += sum(hits)
            if tid in resolved and not resolved[tid]:
                c["unres"] += 1
                c["unres_hit"] += bool(hits)
        if c["runs"] < min_runs:
            continue
        for k, v in c.items():
            per_model[model][k] += v
        print("%-34s %-30s %6d %7d %6d %8.0f%% %10s %7.0f%%" % (
            d.name[:34], model, c["runs"], c["turns"], c["caphit"], 100 * c["runs_hit"] / c["runs"],
            ("%.0f%% of %d" % (100 * c["unres_hit"] / c["unres"], c["unres"])) if c["unres"] else "-",
            100 * c["out_tok_hit"] / max(c["out_tok"], 1)))
    print("\nPER MODEL")
    for m, c in sorted(per_model.items(), key=lambda x: -x[1]["runs"]):
        print("%-30s runs %6d  cap-hit turns %6d of %7d  runs with a hit %3.0f%%  unresolved runs with a hit %s  "
              "output tokens in cap-hit turns %3.0f%%" % (
                  m, c["runs"], c["caphit"], c["turns"], 100 * c["runs_hit"] / c["runs"],
                  ("%.0f%% of %d" % (100 * c["unres_hit"] / c["unres"], c["unres"])) if c["unres"] else "-",
                  100 * c["out_tok_hit"] / max(c["out_tok"], 1)))


if __name__ == "__main__":
    main(sys.argv[1:])
