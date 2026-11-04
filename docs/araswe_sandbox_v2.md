<!-- docs/araswe_sandbox_v2.md contract
WHAT: how the araswe local sandbox image (swebench-sandbox-local:v2) was fixed so the reference patches pass, with the
measured gold-check numbers at each step. Updated in place if the image changes again; numbers are measured, never estimated.
-->
# araswe sandbox v2: from 75/129 to 125/129 (measured 2026-11-04)

## Result

Gold check (reference fix applied, tests run through the real harness, swegemma 0.2.11):

| Image | Hook | Gold | fastapi | httpx | requests | rich |
|---|---|---|---|---|---|---|
| `swebench-sandbox-local:latest` | repaired | 75/129 | 19/67 | – | – | – |
| `v2` + starlette 0.48.0 | debug copy | 121/129 | 65/67 | 1/1 | 9/13 | 46/48 |
| `v2` + 4 wheels (final) | repaired | **125/129** | 66/67 | 1/1 | 12/13 | 46/48 |

Run folder for the final number: `runs/gold_v2_final` (local only).

## Cause

The harness unpacks the newest version of every wheel in `data/wheels` into site-packages (for Starlette: 1.6.0). The
repair step (`kits/swe-agent/sandbox/repair.py`) sees that a snapshot declares an older range, e.g.
`starlette>=0.40.0,<0.49.0`, and swaps in a matching wheel. It can only take that wheel from the image's own `/wheels`
or the shelf `/wheels_extra`, not from `data/wheels`. Neither held the needed versions, so the repair logged
`"no wheel in /wheels satisfies it"` and left the newest version in place. Tests then failed even with the reference fix
(fastapi: `Router.__init__() got an unexpected keyword argument 'on_startup'`; requests: `DID NOT RAISE InvalidURL`,
the Werkzeug 3 case already described in `LOCAL_RULES`).

How it was found: a debug copy of the hook printed the Starlette version and the repair report inside the harness
container. The report's `skipped` list named the missing ranges.

## Fix

Four wheels, copied unchanged from the competition's `data/wheels` into the image's `/wheels`:

| Wheel | Needed by |
|---|---|
| `starlette-0.48.0-py3-none-any.whl` | fastapi snapshots pinning `starlette<0.49.0` |
| `starlette-0.47.3-py3-none-any.whl` | 1 fastapi snapshot pinning `starlette<0.48.0` |
| `werkzeug-2.3.8-py3-none-any.whl` | requests snapshots < 2.32 (`LOCAL_RULES`: `werkzeug<3`) |
| `flask-2.3.3-py3-none-any.whl` | same (`flask<3`, Flask 3 requires Werkzeug 3) |

Rebuild:

```bash
mkdir -p ~/araswe/extra_wheels
cp ~/araswe/data/wheels/{starlette-0.48.0,starlette-0.47.3,flask-2.3.3,werkzeug-2.3.8}-py3-none-any.whl ~/araswe/extra_wheels/
printf 'FROM swebench-sandbox-local:latest\nCOPY *.whl /wheels/\n' > ~/araswe/extra_wheels/Dockerfile
docker build -t swebench-sandbox-local:v2 ~/araswe/extra_wheels
```

Every agent run and gold check must use `IMAGE=swebench-sandbox-local:v2`.

Other local change: `repair.py` `_installed_version` returns None when a package has more than one `.dist-info`
(forces a swap). Not shown to be needed for the 125; kept, and listed here so the diff is complete.

## The 4 remaining failures (exclusions, not sandbox bugs)

| Task | Failure | Reason |
|---|---|---|
| fastapi_14186 | required test skipped | test runs only under the other pydantic major version |
| requests_6757 | `SSLCertVerificationError` | test certificate in the repo has expired |
| rich_3472 | output text differs | expects Python ≤ 3.12 error wording; sandbox is 3.13 |
| rich_3486 | required test skipped | Python-version skipif pair; one side always skips |

Two further tasks pass with an empty patch and are excluded from the agent study, giving 123 usable tasks.
