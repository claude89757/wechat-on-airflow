from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebappObservationDiagnosisScriptTest(unittest.TestCase):
    def test_timeout_wraps_a_real_compose_executable(self):
        source = (ROOT / "scripts" / "diagnose_webapp_observation.sh").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("timeout 8s compose exec", source)
        self.assertIn('timeout "$timeout_seconds" docker compose "$@"', source)
        self.assertIn('timeout "$timeout_seconds" docker-compose "$@"', source)
        self.assertIn("Error checking 大沙河国际网球中心", source)
        self.assertIn("-mmin -180", source)


if __name__ == "__main__":
    unittest.main()
