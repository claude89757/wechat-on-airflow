#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).with_name("_apply_release_hardening_patch.py")
text = path.read_text(encoding="utf-8")
old = '''replace_exact(
    "webapp/src/Prototype.tsx",
    'import {\\n',
    'import * as DropdownMenu from "@radix-ui/react-dropdown-menu";\\nimport {\\n',
)
'''
new = '''replace_exact(
    "webapp/src/Prototype.tsx",
    'import {\\n  ArrowsClockwiseIcon,\\n',
    'import * as DropdownMenu from "@radix-ui/react-dropdown-menu";\\nimport {\\n  ArrowsClockwiseIcon,\\n',
)
'''
if text.count(old) != 1:
    raise SystemExit("release hardening import anchor was not found exactly once")
path.write_text(text.replace(old, new), encoding="utf-8")
Path(__file__).unlink()
