#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "CHANGELOG.md"
text = path.read_text(encoding="utf-8")
marker = "### Changed\n<!-- release-hardening-history-marker -->\n\n"
if text.count(marker) != 1:
    raise SystemExit("historical changelog marker was not found exactly once")
path.write_text(text.replace(marker, "### Changed\n\n"), encoding="utf-8")
(root / "scripts/_prepare_release_hardening_changelog.py").unlink(missing_ok=True)
Path(__file__).unlink()
