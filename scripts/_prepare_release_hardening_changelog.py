#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
text = path.read_text(encoding="utf-8")
needle = "### Changed\n\n"
positions: list[int] = []
start = 0
while True:
    index = text.find(needle, start)
    if index < 0:
        break
    positions.append(index)
    start = index + len(needle)
if len(positions) != 2:
    raise SystemExit(f"expected two changelog Changed headings, found {len(positions)}")
second = positions[1]
marker = "### Changed\n<!-- release-hardening-history-marker -->\n\n"
path.write_text(text[:second] + marker + text[second + len(needle):], encoding="utf-8")
