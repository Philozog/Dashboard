"""Import and route checks in an isolated process/database, without live requests."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class AppSmokeTests(unittest.TestCase):
    def test_routes_and_layouts(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {
                **os.environ,
                "APOTHICAIRE_DB": str(Path(folder) / "test.db"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            result = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).with_name("smoke_app.py"))],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
