"""Release images report the version baked in by CI, not a stale FT_APP_VERSION."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import config
from app.routers.health import health_check


class TestBuildVersion(unittest.TestCase):
    def test_read_build_version(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "VERSION"
            self.assertIsNone(config.read_build_version(path))  # dev: no file
            path.write_text("1.0.5\n")
            self.assertEqual(config.read_build_version(path), "1.0.5")
            path.write_text("  \n")
            self.assertIsNone(config.read_build_version(path))

    def test_baked_version_beats_env(self):
        with patch.object(config, "read_build_version", return_value="1.0.5"):
            s = config.Settings(FT_APP_VERSION="1.1.0")
        self.assertEqual(s.FT_APP_VERSION, "1.0.5")

    def test_env_version_used_without_baked_file(self):
        with patch.object(config, "read_build_version", return_value=None):
            s = config.Settings(FT_APP_VERSION="1.1.0")
        self.assertEqual(s.FT_APP_VERSION, "1.1.0")

    def test_health_reports_version_and_keeps_legacy_keys(self):
        with patch.object(config.settings, "FT_APP_VERSION", "1.0.5"):
            body = health_check()
        self.assertEqual(body, {"Error": 200, "status": "ok", "version": "1.0.5"})


if __name__ == "__main__":
    unittest.main()
