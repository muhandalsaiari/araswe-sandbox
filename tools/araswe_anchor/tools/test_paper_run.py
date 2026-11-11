"""Offline tests of paper_run.py: fake runner, fake translator, temp ledger, no GPU, no docker, nothing written to results/.

usage: python3 -I tools/araswe_anchor/tools/test_paper_run.py
The fake runner reads a scenario file: {"run_id/task": row overrides, or "crash" to leave no row}.
"""
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import paper_run as pr  # noqa: E402

FAKE_RUN = r'''
import json, os, sys
run, ids = os.environ["RUN_ID"], sys.argv[3].split("+")
sc = json.load(open(os.environ["SCENARIO"]))
with open(os.environ["CALLS"], "a") as f: f.write(json.dumps([run, ids, os.environ.get("TASKS_JSONL", "")]) + "\n")
for t in ids:
    o = sc.get(f"{run}/{t}", {})
    if o == "crash":
        sc[f"{run}/{t}"] = {}; json.dump(sc, open(os.environ["SCENARIO"], "w")); sys.exit(1)
    with open(os.environ["LEDGER"], "a") as f:
        f.write(json.dumps({"id": t, "run_id": run, "tool_calls": 12, "harness_error": None, **o}) + "\n")
'''
FAKE_TF = r'''
import os, sys
i = open(sys.argv[3]).read().strip()
if i in os.environ.get("TF_BAD", "").split(): open(sys.argv[2], "w").close(); sys.exit(1)
open(sys.argv[2], "w").write('{"instance_id": "%s"}\n' % i)
'''
ABORT = {"harness_error": "Sandbox execution error: litellm.BadRequestError: OpenAIException - Error code: 400 - {'error': 'terminated'}", "tool_calls": 17}
ZERO = {"tool_calls": 0, "harness_error": "Sandbox execution error: litellm.InternalServerError: Connection error."}
BUDGET = {"tool_calls": 30, "harness_error": "Agent exceeded tool call budget (30 calls)"}
FAILS = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


class Sandbox:
    def __init__(self, name, tasks, scenario=None, tf_bad=""):
        self.t = Path(tempfile.mkdtemp())
        self.prefix = f"zz_test_{name}"
        (self.t / "run.py").write_text(FAKE_RUN)
        (self.t / "tf.py").write_text(FAKE_TF)
        (self.t / "tasks.txt").write_text("\n".join(tasks) + "\n")
        (self.t / "sc.json").write_text(json.dumps(scenario or {}))
        (self.t / "up").write_text("up")
        self.env = {**os.environ, "LEDGER": str(self.t / "ledger"), "SCENARIO": str(self.t / "sc.json"), "CALLS": str(self.t / "calls"),
                    "PAPER_RUN_CMD": f"python3 -I {self.t}/run.py", "PAPER_TF_CMD": f"python3 -I {self.t}/tf.py",
                    "PAPER_HEALTH_FILE": str(self.t / "up"), "TF_BAD": tf_bad}

    def go(self, *extra):
        cmd = ["python3", "-I", str(HERE / "paper_run.py"), "--go", "--prefix", self.prefix, "--no-retest", "--block", "2",
               "--tasks", str(self.t / "tasks.txt"), *extra]
        return subprocess.run(cmd, env=self.env, capture_output=True, text=True, timeout=120)

    def calls(self):
        f = self.t / "calls"
        return [json.loads(x) for x in open(f)] if f.exists() else []

    def rows(self):
        f = self.t / "ledger"
        return [json.loads(x) for x in open(f)] if f.exists() else []

    def close(self):
        shutil.rmtree(self.t, ignore_errors=True)
        shutil.rmtree(ROOT / "runs" / self.prefix, ignore_errors=True)


def real_rows():
    led = ROOT / "results/task_runs.jsonl"
    pilot = [json.loads(x) for x in open(led) if '"run_id": "paper_pilot_t0_' in x]
    flagged = [r for r in pilot if pr.rerun_reason(r)]
    check("pilot: 40 rows", len(pilot) == 40)
    check("pilot: exactly the 3 known aborts flagged", len(flagged) == 3 and all(pr.rerun_reason(r) == "server_abort" for r in flagged))
    kinds = collections.Counter()
    for x in open(led):
        r = json.loads(x)
        e = str(r.get("harness_error") or r.get("error") or "")
        key = next((k for k in ("tool call budget", "turns budget", "session timeout", "without calling submit_patch") if k in e), None)
        if key and r.get("tool_calls"):
            kinds[(key, pr.rerun_reason(r))] += 1
    check("whole ledger: agent's own failures with calls never flagged", kinds and all(k[1] is None for k in kinds))
    print("     ", dict(kinds))


def classifier():
    r = pr.rerun_reason
    check("0 calls + no submit_patch is rerun", r({"tool_calls": 0, "harness_error": "Agent completed execution without calling submit_patch."}) == "zero_calls")
    check("exception row without tool_calls is rerun", r({"error": "AttributeError: 'NoneType' object has no attribute 'qsize'"}) == "zero_calls")
    check("connection error mid-run is rerun", r({"tool_calls": 9, "harness_error": ZERO["harness_error"]}) == "server_abort")
    check("clean row not rerun", r({"tool_calls": 9, "harness_error": None}) is None)
    check("budget not rerun", r(BUDGET) is None)
    check("session timeout not rerun", r({"tool_calls": 9, "harness_error": "Agent exceeded session timeout (25.0 min)"}) is None)
    check("docker read timeout not rerun", r({"tool_calls": 9, "harness_error": "Evaluation error: UnixHTTPConnectionPool(host='localhost', port=None): Read timed out. (read timeout=60)"}) is None)


def flows():
    s = Sandbox("happy", ["a", "b", "c"])
    p = s.go()
    order = [c[0].removeprefix(s.prefix + "_") for c in s.calls()]
    check("happy: exit 0", p.returncode == 0)
    check("happy: arms in PREREG order, block by block", order == ["en", "ar", "en_anchor", "ar_anchor", "ar_tf"] * 2)
    check("happy: AR arm uses ar_mix_full", str(pr.AR_MIX) == s.calls()[1][2])
    check("happy: EN arm has no task file", s.calls()[0][2] == "")
    check("happy: TF arm has its block file", s.calls()[4][2].endswith("tf/block01.jsonl"))
    n = len(s.rows())
    s.go()
    check("restart when finished adds nothing", len(s.rows()) == n == 15)
    s.close()

    pre = "zz_test_rerun"
    s = Sandbox("rerun", ["a", "b"], {f"{pre}_ar/a": ABORT, f"{pre}_ar/b": BUDGET, f"{pre}_en/b": ZERO, f"{pre}_en_rerun/b": ZERO})
    p = s.go()
    runs = collections.Counter(r["run_id"].removeprefix(pre + "_") for r in s.rows())
    check("rerun: abort gets one rerun, budget none", runs["ar_rerun"] == 1 and [r["id"] for r in s.rows() if r["run_id"].endswith("_ar_rerun")] == ["a"])
    check("rerun: first-try rows kept", runs["ar"] == 2 and runs["en"] == 2)
    check("rerun: second failure, no third try", runs["en_rerun"] == 1 and "SECOND_FAILURE" in p.stdout)
    n = len(s.rows())
    s.go()
    check("rerun: restart repeats no rerun", len(s.rows()) == n)
    s.close()

    pre = "zz_test_crash"
    s = Sandbox("crash", ["a", "b"], {f"{pre}_en/b": "crash"})
    p = s.go()
    check("crash: task with no row is relaunched, not lost", p.returncode == 0 and sum(r["run_id"] == f"{pre}_en" for r in s.rows()) == 2)
    s.close()

    s = Sandbox("stop", ["a", "b", "c", "d"])
    p = s.go("--hours", "0.0000001")
    arms = collections.Counter(r["run_id"] for r in s.rows())
    check("stop: first block finishes all five arms, next not started",
          "STOP_ADDING block02" in p.stdout and len(arms) == 5 and set(arms.values()) == {2})
    s.close()

    pre = "zz_test_resume"
    s = Sandbox("resume", ["a", "b", "c", "d"])
    (s.t / "ledger").write_text(json.dumps({"id": "a", "run_id": f"{pre}_en", "tool_calls": 5}) + "\n")
    (ROOT / "runs" / pre).mkdir(parents=True, exist_ok=True)
    (ROOT / "runs" / pre / "clock.jsonl").write_text(json.dumps({"what": "x", "seconds": 7200}) + "\n")
    p = s.go("--hours", "1")
    arms = collections.Counter(r["run_id"] for r in s.rows())
    check("stop: a block started before the limit still finishes after a restart",
          len(arms) == 5 and set(arms.values()) == {2} and "STOP_ADDING block02" in p.stdout)
    s.close()

    s = Sandbox("tf", ["a", "b"], tf_bad="b")
    p = s.go()
    tf = [r["id"] for r in s.rows() if r["run_id"].endswith("_ar_tf")]
    check("tf: failed translation drops only that task from the arm", tf == ["a"] and "TF_FAILED b" in p.stdout)
    check("tf: run goes on", p.returncode == 0)
    s.close()

    s = Sandbox("down", ["a"])
    (s.t / "up").write_text("down")
    p = s.go("--max-wait-hours", "0", "--wait-seconds", "0.01")
    check("outage: nothing launched, exit 4, no rows", p.returncode == 4 and not s.rows())
    (s.t / "up").write_text("up")
    p = s.go()
    check("outage: relaunch continues", p.returncode == 0 and len(s.rows()) == 5)
    s.close()

    bad = subprocess.run(["python3", "-I", str(HERE / "paper_run.py")], capture_output=True, text=True)
    check("no --go: dry run only", bad.returncode == 0 and "DRY RUN" in bad.stdout and "115 tasks" in bad.stdout and "23 blocks" in bad.stdout)
    print(bad.stdout[:600])


classifier()
real_rows()
flows()
print("FAILED:" if FAILS else "ALL PASSED", FAILS or "")
sys.exit(bool(FAILS))
