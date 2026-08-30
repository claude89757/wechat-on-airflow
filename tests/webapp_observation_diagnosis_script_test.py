from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_timeout_wraps_a_real_compose_executable() -> None:
    source = (ROOT / "scripts" / "diagnose_webapp_observation.sh").read_text(
        encoding="utf-8"
    )

    assert "timeout 8s compose exec" not in source
    assert 'timeout "$timeout_seconds" docker compose "$@"' in source
    assert 'timeout "$timeout_seconds" docker-compose "$@"' in source
    assert "Error checking 大沙河国际网球中心" in source
    assert "-mmin -180" in source
