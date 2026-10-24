from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import github_release_gate as gate  # noqa: E402

SHA = "1" * 40


def check(identifier: int, name: str = "other", conclusion: str = "success") -> dict:
    return {
        "id": identifier,
        "name": name,
        "head_sha": SHA,
        "status": "completed",
        "conclusion": conclusion,
    }


def page(total: int, items: list) -> io.BytesIO:
    return io.BytesIO(json.dumps({"total_count": total, "check_runs": items}).encode())


def test_required_verify_after_one_hundred_other_checks():
    first = [check(i) for i in range(100, 200)]
    last = [check(1, "verify"), check(2), check(3), check(4)]
    with patch.object(
        gate.urllib.request,
        "urlopen",
        side_effect=[page(104, first), page(104, last)],
    ) as request:
        result = gate.fetch_check_runs("owner/repo", SHA, "test-only")
    assert gate.required_check_result(result, "verify")["ok"]
    assert len(result["check_runs"]) == 104
    assert [call.args[0].full_url.rsplit("page=", 1)[1] for call in request.call_args_list] == [
        "1",
        "2",
    ]


def test_later_page_failure_is_not_replaced_by_older_success():
    first = [check(1, "verify")]
    with patch.object(
        gate.urllib.request,
        "urlopen",
        side_effect=[page(2, first), page(2, [check(2, "verify", "failure")])],
    ):
        result = gate.fetch_check_runs("owner/repo", SHA, "test-only")
    assert gate.required_check_result(result, "verify")["conclusion"] == "failure"
    assert not gate.required_check_result(result, "verify")["ok"]


@pytest.mark.parametrize(
    "payload",
    [[], {}, {"total_count": True, "check_runs": []}, {"total_count": 1, "check_runs": {}}],
)
def test_malformed_metadata_never_passes(payload):
    with patch.object(
        gate.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())
    ):
        with pytest.raises(gate.OpsError, match="pagination metadata"):
            gate.fetch_check_runs("owner/repo", SHA, "test-only")


@pytest.mark.parametrize(
    "second",
    [
        page(2, []),
        page(3, [check(2)]),
        page(2, [check(1)]),
        page(2, [{**check(2), "head_sha": "2" * 40}]),
    ],
)
def test_incomplete_changed_duplicate_or_wrong_commit_evidence_fails(second):
    with patch.object(gate.urllib.request, "urlopen", side_effect=[page(2, [check(1)]), second]):
        with pytest.raises(gate.OpsError):
            gate.fetch_check_runs("owner/repo", SHA, "test-only")


def test_missing_check_remains_missing():
    with patch.object(gate.urllib.request, "urlopen", return_value=page(0, [])):
        result = gate.fetch_check_runs("owner/repo", SHA, "test-only")
    assert not gate.required_check_result(result, "verify")["present"]


def test_bad_commit_never_sends_credentials():
    with patch.object(gate.urllib.request, "urlopen") as request:
        with pytest.raises(gate.OpsError):
            gate.fetch_check_runs("owner/repo", "main?injected=1", "test-only")
    request.assert_not_called()
