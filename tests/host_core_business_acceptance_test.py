from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text()


def test_one_control_plane_and_no_one_time_production_scheduler():
    assert not (ROOT / ".github/workflows/production-host-core-v070.yml").exists()
    ship = read(".github/workflows/production-ship.yml")
    assert "operation: full-cutover" in ship
    assert "operation: activate-workers" in ship
    assert "operation: acceptance" in ship
    assert "operation: pause" in ship


def test_business_acceptance_precedes_immutable_version_release():
    ship = read(".github/workflows/production-ship.yml")
    assert "needs: [deploy, acceptance]" in ship
    assert "needs.acceptance.result == 'success'" in ship
    assert (
        ship.index("  host_core_cutover:")
        < ship.index("  deploy:")
        < ship.index("  natural_cycles:")
        < ship.index("  acceptance:")
        < ship.index("  tag:")
    )


def test_acceptance_checks_records_not_sleep_or_successful_restart():
    health = read("src/wechat_airflow/host_core/health.py")
    assert "required = 3 if is_venue else 1" in health
    assert "len(venue_components) == 26" in health
    assert "naturalEmailProviderDelivered" in health
    assert "naturalWeChatDelivered" in health
    assert "migrationReconciled" in health
    assert '"complete": True' in health
    script = read("scripts/host_core_release.sh")
    assert ".complete == true and .ok == true and .success == true" in script
