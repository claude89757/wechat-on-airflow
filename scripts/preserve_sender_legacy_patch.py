"""Preserve the reviewed September idle-session hotpatch before exact-SHA release."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

LEGACY_SHA256 = "ad5929d40ca1ba56ef5f46f5f5d16fa12fc15462db96a78d1eaf6973e283a540"
LEGACY_PATH = "sender_agent/app.py"


def preserve(repo: Path, backups: Path, *, apply: bool, expected_hash: str = LEGACY_SHA256) -> str:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    dirty = git("diff", "--name-only", "HEAD").splitlines()
    if not dirty:
        return ""
    if dirty != [LEGACY_PATH] or git("diff", "--cached", "--name-only"):
        raise RuntimeError("Unreviewed sender worktree changes; refusing deployment")
    source = repo / LEGACY_PATH
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise RuntimeError("Sender hotpatch fingerprint changed; refusing deployment")
    if not apply:
        return ""
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix="legacy-idle-", dir=backups))
    backup = directory / "app.py"
    backup.write_bytes(content)
    backup.chmod(0o600)
    (directory / "commit").write_text(git("rev-parse", "HEAD") + "\n")
    # Only this reviewed file is reset; untracked files and all data are untouched.
    subprocess.run(["git", "-C", str(repo), "restore", "--", LEGACY_PATH], check=True)
    return str(backup)


if __name__ == "__main__":
    import sys

    os.umask(0o077)
    print(
        preserve(
            Path(sys.argv[1]), Path("/var/backups/wechat-sender"), apply=sys.argv[2] == "apply"
        )
    )
