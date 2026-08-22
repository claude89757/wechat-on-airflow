from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass

COMMAND_RE = re.compile(
    r"^\s*/release\s+(preflight|apply)\s+([0-9a-fA-F]{40})(?:\s+sender=(true|false))?\s*$"
)


@dataclass(frozen=True)
class ReleaseCommand:
    mode: str
    target_commit: str
    include_sender: bool


def parse_release_command(body: str) -> ReleaseCommand:
    match = COMMAND_RE.fullmatch(body)
    if not match:
        raise ValueError(
            "expected: /release <preflight|apply> <40-char-sha> [sender=true|false]"
        )
    mode, target_commit, sender = match.groups()
    return ReleaseCommand(
        mode=mode,
        target_commit=target_commit.lower(),
        include_sender=sender == "true" if sender is not None else False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a production release ChatOps command.")
    parser.add_argument("command")
    parser.add_argument("--format", choices=("json", "github-output"), default="json")
    args = parser.parse_args()

    command = parse_release_command(args.command)
    if args.format == "json":
        print(json.dumps(asdict(command), separators=(",", ":")))
        return

    print(f"mode={command.mode}")
    print(f"target_commit={command.target_commit}")
    print(f"include_sender={'true' if command.include_sender else 'false'}")


if __name__ == "__main__":
    main()
