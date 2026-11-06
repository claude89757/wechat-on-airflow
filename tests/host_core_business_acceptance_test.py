from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text()


def test_one_control_plane_and_no_one_time_production_scheduler():
    assert not (ROOT / ".github/workflows/production-host-core-v070.yml").exists()
    ship = read(".github/workflows/production-ship.yml")
    assert "inputs.version == '0.7.0' && 'full-cutover' || 'routine-upgrade'" in ship
    assert "operation: activate-workers" in ship
    assert "operation: acceptance" in ship
    assert "operation: pause" in ship


def test_worker_activation_precedes_immutable_version_release():
    ship = read(".github/workflows/production-ship.yml")
    assert "needs: [deploy, natural_cycles]" in ship
    assert "needs.natural_cycles.result == 'success'" in ship
    assert "needs: [deploy, acceptance]" not in ship
    assert "needs.acceptance.result == 'success'" not in ship
    assert (
        ship.index("  host_core_cutover:")
        < ship.index("  deploy:")
        < ship.index("  natural_cycles:")
        < ship.index("  acceptance:")
        < ship.index("  tag:")
    )


def test_acceptance_checks_records_not_sleep_or_successful_restart():
    health = read("src/wechat_airflow/host_core/health.py")
    controller = read("scripts/host_core_production.py")
    assert "required = 3 if is_venue else 1" in health
    assert "len(venue_components) == len(VENUES)" in health
    assert '"all26VenueObservations"' in health
    assert '"all26VenueObservations"' in controller
    assert '"all27VenueObservations"' not in controller
    assert "naturalEmailProviderDelivered" in health
    assert "naturalWeChatDelivered" in health
    assert "migrationReconciled" in health
    assert '"complete": True' in health
    script = read("scripts/host_core_release.sh")
    assert ".complete == true and .ok == true and .success == true" in script
