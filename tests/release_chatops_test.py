from __future__ import annotations

import pytest

from scripts.parse_release_command import parse_release_command


def test_parse_preflight_defaults_sender_off() -> None:
    sha = "A" * 40
    command = parse_release_command(f"/release preflight {sha}")
    assert command.mode == "preflight"
    assert command.target_commit == sha.lower()
    assert command.include_sender is False


def test_parse_apply_with_sender_enabled() -> None:
    sha = "b" * 40
    command = parse_release_command(f"  /release apply {sha} sender=true  ")
    assert command.mode == "apply"
    assert command.target_commit == sha
    assert command.include_sender is True


@pytest.mark.parametrize(
    "body",
    [
        "/release deploy " + "a" * 40,
        "/release apply abc123",
        "/release apply " + "a" * 40 + " sender=yes",
        "please /release apply " + "a" * 40,
        "/release apply " + "a" * 40 + " extra",
    ],
)
def test_reject_invalid_or_ambiguous_commands(body: str) -> None:
    with pytest.raises(ValueError):
        parse_release_command(body)
