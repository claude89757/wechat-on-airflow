"""Hold the existing per-phone flock until the MCP process closes stdin."""

import fcntl
import os
import re
import sys
from pathlib import Path

serial, directory = sys.argv[1:]
if not re.fullmatch(r"[A-Za-z0-9._:-]+", serial):
    raise SystemExit(2)
with (Path(directory) / f"device-{serial}.lock").open("a+") as handle:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("busy", flush=True)
        raise SystemExit(3) from None
    if os.fstat(handle.fileno()).st_uid == os.getuid():
        os.fchmod(handle.fileno(), 0o660)
    print("ready", flush=True)
    sys.stdin.buffer.read()
