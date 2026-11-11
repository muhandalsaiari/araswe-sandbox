"""Runner for the pre-registered agent study (tools/araswe_anchor/paper/PREREG.md, Part 1). Standard library only.

usage: python3 -I tools/araswe_anchor/tools/paper_run.py            # dry run: prints the plan, launches nothing
       python3 -I tools/araswe_anchor/tools/paper_run.py --go       # runs the study; only after the PREREG hash is on the forum
       ... --go --prefix paper_runnertest --tasks tools/araswe_anchor/paper/pilot_1.txt --no-retest   # runner test

Order: blocks of tasks_60.txt through all five arms, then the retest (EN, AR), then blocks of tasks_ext.txt.
No new block starts after --hours of run time; a started block always finishes, so a stop leaves no half-finished arms.

Everything is read back from the ledger, so a relaunch with the same prefix continues where it stopped.
Run ids: <prefix>_<arm> (first try, kept for the sensitivity table), <prefix>_<arm>_rerun (the one rerun),
<prefix>_retest_<arm>, <prefix>_retest_<arm>_rerun.

Rerun rule (PREREG, Failed runs), in rerun_reason(): 0 tool calls, or a server abort. Budget, timeout and no-submit_patch rows
with tool calls are the agent's own and never rerun. There is never a third try. Before every arm and rerun the model server
must answer a real completion, so an outage waits instead of using up the rerun.

Test doubles for tools/araswe_anchor/tools/test_paper_run.py: PAPER_RUN_CMD, PAPER_TF_CMD, PAPER_HEALTH_FILE, LEDGER.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAPER = ROOT / "tools/araswe_anchor/paper"
PREREG_SHA = "b31d8fd93839a2672de664704e7577670a22b7570d39d57e94c328e8865243d7"
AR_MIX = Path.home() / "araswe/translations/ar_mix_full.jsonl"
BASE, ANCHOR = "agents/araswe_paper_base", "agents/araswe_paper_anchor"
ARMS = [("en", BASE, "en"), ("ar", BASE, "ar"), ("en_anchor", ANCHOR, "en"), ("ar_anchor", ANCHOR, "ar"), ("ar_tf", BASE, "tf")]
RETEST_ARMS = [("retest_en", BASE, "en"), ("retest_ar", BASE, "ar")]
SERVER_ENV = {"IMAGE": "swebench-sandbox-local:v2", "MODEL_PORT": "1235", "SERVED_MODEL_NAME": "google/gemma-4-12b-qat",
              "CONCURRENCY": "2", "KAGGLE_CLOCK": "off"}
RUN_CMD = "envs/harness/bin/python -I kits/swe-agent/run/run_tasks.py"
TF_CMD = "python3 -I tools/araswe_anchor/tools/translate_first.py"
SERVER_ABORT = re.compile(r"litellm\.(BadRequestError|InternalServerError|ContextWindowExceededError|Timeout|APIConnectionError"
                          r"|ServiceUnavailableError)|Error code: [45]\d\d|\bterminated\b")
MAX_LAUNCHES = 3  # run_tasks itself crashing leaves tasks with no row; those are not tries, but a repeat crash needs a person


def rerun_reason(row):
    """None, 'zero_calls' or 'server_abort'. Zero calls comes first: it is rerun whatever the error text says."""
    if not row.get("tool_calls"):
        return "zero_calls"
    if SERVER_ABORT.search(str(row.get("harness_error") or row.get("error") or "")):
        return "server_abort"
    return None


def say(msg):
    print(f"PAPER {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())} {msg}", flush=True)


def read_ids(path):
    return [x.strip() for x in open(path) if x.strip()]


def ledger_rows(prefix):
    """{run_id: {task id: row}} for this prefix. The first row of a task wins, as a resumed run writes none after it."""
    path = Path(os.environ.get("LEDGER") or ROOT / "results/task_runs.jsonl")
    out = {}
    if not path.exists():
        return out
    mark = f'"run_id": "{prefix}_'
    for line in open(path):
        if mark in line:
            r = json.loads(line)
            out.setdefault(r["run_id"], {}).setdefault(r["id"], r)
    return out


def healthy():
    if os.environ.get("PAPER_HEALTH_FILE"):
        return Path(os.environ["PAPER_HEALTH_FILE"]).read_text().strip() == "up"
    body = {"model": SERVER_ENV["SERVED_MODEL_NAME"], "max_tokens": 1, "temperature": 0, "messages": [{"role": "user", "content": "ok"}]}
    req = urllib.request.Request(f"http://localhost:{SERVER_ENV['MODEL_PORT']}/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return bool(json.load(r).get("choices"))
    except Exception as exc:
        say(f"SERVER_DOWN {type(exc).__name__}: {str(exc)[:120]}")
        return False


def live_runs():
    mine, pid = set(), os.getpid()  # this process and its parents (the watchdog's command line names this script too)
    while pid > 1:
        mine.add(pid)
        pid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
    found = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit() and int(p.name) not in mine:
            try:
                cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if "run_tasks.py" in cmd or "paper_run.py" in cmd:
                found.append(f"{p.name}: {cmd[:120]}")
    return found


class Study:
    def __init__(self, a):
        self.a = a
        self.dir = ROOT / "runs" / a.prefix
        self.dir.mkdir(parents=True, exist_ok=True)
        self.tf = self.dir / "tf"
        self.tf.mkdir(exist_ok=True)
        self.state = self.dir / "clock.jsonl"

    def elapsed(self):
        if not self.state.exists():
            return 0.0
        return sum(json.loads(x)["seconds"] for x in open(self.state))

    def tick(self, what, seconds):
        with open(self.state, "a") as fh:
            fh.write(json.dumps({"what": what, "seconds": round(seconds, 3)}) + "\n")

    def wait_server(self):
        t0 = time.time()
        while not healthy():
            if time.time() - t0 > self.a.max_wait_hours * 3600:
                say("OUTAGE server down past the wait limit, stopping. Relaunch with the same prefix to continue.")
                sys.exit(4)
            say("WAIT server not answering, nothing launched")
            time.sleep(self.a.wait_seconds)

    def launch(self, run_id, agent, text, ids, label):
        """Runs ids under run_id until each has a ledger row. text: en, ar, or a task file path."""
        for attempt in range(1, MAX_LAUNCHES + 1):
            todo = [t for t in ids if t not in ledger_rows(self.a.prefix).get(run_id, {})]
            if not todo:
                return
            self.wait_server()
            env = {**os.environ, **SERVER_ENV, "RUN_ID": run_id}
            if text == "ar":
                env["TASKS_JSONL"] = str(AR_MIX)
            elif text != "en":
                env["TASKS_JSONL"] = str(text)
            cmd = shlex.split(os.environ.get("PAPER_RUN_CMD", RUN_CMD)) + [agent, f"runs/{run_id}", "+".join(todo)]
            say(f"RUN {run_id} {label} n={len(todo)} try={attempt}")
            t0 = time.time()
            rc = subprocess.call(cmd, cwd=ROOT, env=env)
            self.tick(run_id, time.time() - t0)
            if rc:
                say(f"RUNNER_EXIT {run_id} rc={rc}")
        missing = [t for t in ids if t not in ledger_rows(self.a.prefix).get(run_id, {})]
        if missing:
            say(f"FATAL {run_id}: no ledger row after {MAX_LAUNCHES} launches for {missing}")
            sys.exit(3)

    def run_arm(self, name, agent, text, ids, label):
        first = f"{self.a.prefix}_{name}"
        self.launch(first, agent, text, ids, label)
        rows = ledger_rows(self.a.prefix).get(first, {})
        flagged = {t: rerun_reason(rows[t]) for t in ids if rerun_reason(rows[t])}
        if flagged:
            say(f"RERUN {first} {flagged}")
            self.launch(f"{first}_rerun", agent, text, sorted(flagged), label)
            second = ledger_rows(self.a.prefix).get(f"{first}_rerun", {})
            lost = sorted(t for t in flagged if rerun_reason(second[t]))
            if lost:
                say(f"SECOND_FAILURE {first} {lost} count as 0, no third try")

    def tf_file(self, ids, label):
        """Task file for the AR+TF arm and the ids it covers. Each issue is translated once; a rerun reuses that text."""
        kept = []
        for i in ids:
            out = self.tf / f"{i}.jsonl"
            if out.exists() and out.stat().st_size:
                kept.append(i)
                continue
            if (self.tf / f"{i}.failed").exists():
                continue
            idf = self.tf / f"{i}.id"
            idf.write_text(i + "\n")
            for attempt in (1, 2):
                self.wait_server()
                t0 = time.time()
                rc = subprocess.call(shlex.split(os.environ.get("PAPER_TF_CMD", TF_CMD)) + [str(AR_MIX), str(out), str(idf)],
                                     cwd=ROOT, env={**os.environ, **SERVER_ENV})
                self.tick(f"tf_{i}", time.time() - t0)
                if rc == 0 and out.exists() and out.stat().st_size:
                    kept.append(i)
                    break
                out.unlink(missing_ok=True)
            else:
                (self.tf / f"{i}.failed").write_text("translate_first failed twice\n")
                say(f"TF_FAILED {i}: not in the AR+TF arm, so outside the analysis (complete in all five arms only)")
        merged = self.tf / f"{label}.jsonl"
        merged.write_text("".join((self.tf / f"{i}.jsonl").read_text() for i in kept))
        return merged, kept

    def started(self, ids):
        rows = ledger_rows(self.a.prefix)
        return any(t in rows.get(f"{self.a.prefix}_{name}", {}) for name, _, _ in ARMS for t in ids)

    def done(self, ids):
        rows = ledger_rows(self.a.prefix)
        for name, _, text in ARMS:
            first, second = rows.get(f"{self.a.prefix}_{name}", {}), rows.get(f"{self.a.prefix}_{name}_rerun", {})
            for t in ids:
                if text == "tf" and (self.tf / f"{t}.failed").exists():
                    continue
                if t not in first or (rerun_reason(first[t]) and t not in second):
                    return False
        return True

    def block(self, n, ids):
        label = f"block{n:02d}"
        for name, agent, text in ARMS:
            arm_ids, source = ids, text
            if text == "tf":
                source, arm_ids = self.tf_file(ids, label)
            if arm_ids:
                self.run_arm(name, agent, source, arm_ids, label)
        say(f"BLOCK_DONE {label} n={len(ids)} run_hours={self.elapsed() / 3600:.2f}")

    def retest(self, ids):
        for name, agent, text in RETEST_ARMS:
            self.run_arm(name, agent, text, ids, "retest")
        say(f"RETEST_DONE n={len(ids)} run_hours={self.elapsed() / 3600:.2f}")


def units(a):
    """The planned order: ('block', n, ids) and ('retest', None, ids)."""
    lists = [read_ids(f) for f in a.tasks]
    plan, n = [], 0
    for k, ids in enumerate(lists):
        for i in range(0, len(ids), a.block):
            n += 1
            plan.append(("block", n, ids[i:i + a.block]))
        if k == 0 and not a.no_retest:
            plan.append(("retest", None, read_ids(PAPER / "retest_10.txt")))
    return plan


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--go", action="store_true")
    p.add_argument("--prefix", default="paper_full")
    p.add_argument("--tasks", nargs="+", default=[str(PAPER / "tasks_60.txt"), str(PAPER / "tasks_ext.txt")])
    p.add_argument("--block", type=int, default=5)
    p.add_argument("--hours", type=float, default=60.0)
    p.add_argument("--no-retest", action="store_true")
    p.add_argument("--max-wait-hours", type=float, default=8.0)
    p.add_argument("--wait-seconds", type=float, default=120.0)
    a = p.parse_args()

    sha = hashlib.sha256((PAPER / "PREREG.md").read_bytes()).hexdigest()
    if sha != PREREG_SHA:
        sys.exit(f"PREREG.md hash {sha} is not the registered one, nothing launched")
    plan = units(a)
    if not a.go:
        n = sum(len(u[2]) for u in plan if u[0] == "block")
        print(f"DRY RUN, nothing launched. PREREG hash ok. {n} tasks, {sum(u[0] == 'block' for u in plan)} blocks of {a.block}, "
              f"stop after {a.hours} h, prefix {a.prefix}")
        for kind, num, ids in plan:
            print(f"  {kind} {num or ''} n={len(ids)}: {' '.join(ids[:3])} ...")
        return
    live = [x for x in live_runs() if not os.environ.get("PAPER_RUN_CMD")]
    if live:
        sys.exit("live runs found, nothing launched:\n" + "\n".join(live))

    s = Study(a)
    say(f"START prefix={a.prefix} prereg={sha[:12]} units={len(plan)} run_hours={s.elapsed() / 3600:.2f}")
    stopped = False
    for kind, num, ids in plan:
        if kind == "retest":
            s.retest(ids)
        elif s.done(ids):
            continue
        elif s.started(ids):
            s.block(num, ids)
        elif stopped or s.elapsed() >= a.hours * 3600:
            stopped = True
            say(f"STOP_ADDING block{num:02d} not started, run_hours={s.elapsed() / 3600:.2f}")
        else:
            s.block(num, ids)
    say(f"ALL_DONE run_hours={s.elapsed() / 3600:.2f}")


if __name__ == "__main__":
    main()
