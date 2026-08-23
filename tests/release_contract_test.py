from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release_contract.py"


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_release_contract_validates_versions_and_extracts_one_section(tmp_path: Path):
    write(tmp_path, "pyproject.toml", '[project]\nname = "example"\nversion = "1.2.3"\n')
    write(tmp_path, "src/wechat_airflow/__init__.py", '__version__ = "1.2.3"\n')
    write(
        tmp_path,
        "CHANGELOG.md",
        "# Changelog\n\n## [1.2.3] - 2026-08-23\n\n- Current.\n\n"
        "## [1.2.2] - 2026-08-22\n\n- Old.\n",
    )
    notes = tmp_path / "notes.md"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--version",
            "1.2.3",
            "--notes-output",
            str(notes),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert notes.read_text(encoding="utf-8") == "## [1.2.3] - 2026-08-23\n\n- Current.\n"
