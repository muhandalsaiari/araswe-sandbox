"""Build submission.zip from an agent folder, byte-for-byte the way the public notebook does it.

usage: python3 -I tools/build_sub_zip.py <agent_dir> <out.zip>
Fixed timestamps and file modes, sorted names, so the same files always give the same sha256.
Refuses a prompt containing braces (ADK templating eats them).
"""
import hashlib
import sys
import zipfile
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
files = {p.relative_to(src).as_posix(): p.read_bytes() for p in sorted(src.rglob("*")) if p.is_file()}
for name, data in files.items():
    if name.startswith("prompts/") and (b"{" in data or b"}" in data):
        raise SystemExit(f"{name}: contains a brace; ADK templating would eat it")
with zipfile.ZipFile(dst, "w") as zf:
    for name, data in sorted(files.items()):
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        zf.writestr(info, data)
with zipfile.ZipFile(dst) as zf:
    assert zf.testzip() is None and set(zf.namelist()) == set(files)
print("files:", ", ".join(sorted(files)))
print("zip:", dst)
print("sha256:", hashlib.sha256(dst.read_bytes()).hexdigest())
