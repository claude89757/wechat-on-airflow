import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preserve_sender_legacy_patch import preserve  # noqa: E402


def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    source = repo / "sender_agent/app.py"
    source.parent.mkdir()
    source.write_text("original\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
        check=True,
    )
    source.write_text("reviewed patch\n")
    return repo, source, hashlib.sha256(source.read_bytes()).hexdigest()


def test_preserves_exact_patch_and_untracked_files_before_restore(tmp_path):
    repo, source, digest = repository(tmp_path)
    untracked = repo / "data"
    untracked.write_text("must survive")
    backups = tmp_path / "backups"
    assert preserve(repo, backups, apply=False, expected_hash=digest) == ""
    assert source.read_text() == "reviewed patch\n"
    assert not backups.exists()
    saved = Path(preserve(repo, backups, apply=True, expected_hash=digest))
    assert saved.read_text() == "reviewed patch\n"
    assert saved.stat().st_mode & 0o777 == 0o600
    assert source.read_text() == "original\n"
    assert untracked.read_text() == "must survive"
    assert preserve(repo, backups, apply=True, expected_hash=digest) == ""


def test_unknown_drift_is_never_removed(tmp_path):
    repo, source, _ = repository(tmp_path)
    with pytest.raises(RuntimeError, match="fingerprint"):
        preserve(repo, tmp_path / "backups", apply=True)
    assert source.read_text() == "reviewed patch\n"
    assert not (tmp_path / "backups").exists()
