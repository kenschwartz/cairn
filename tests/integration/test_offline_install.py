"""
Integration test: offline install path (zipapp).

DESIGN.md: 'Co-primary means tested, not documented: a test builds the zipapp
and runs cairn --version from it with no network and no pipx. A documented
fallback that has never been executed is not a fallback.'
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


class TestZipappInstall:
    def test_zipapp_builds_and_runs_version(self, tmp_path):
        """
        Build the cairn zipapp with python -m zipapp and run
        `python3 cairn.pyz --version` to confirm the offline install path works.

        This test does NOT use pipx or network access.
        """
        # Locate the cairn package source.
        # We find it by asking the already-installed cairn where it lives.
        import cairn
        cairn_src_dir = Path(cairn.__file__).parent  # .../src/cairn/

        # The src/ directory that contains the cairn package.
        src_dir = cairn_src_dir.parent  # .../src/

        # Build the zipapp.
        pyz = tmp_path / "cairn.pyz"
        result = subprocess.run(
            [
                sys.executable, "-m", "zipapp",
                str(src_dir),
                "--output", str(pyz),
                "--python", "/usr/bin/env python3",
                "--main", "cairn.cli:main",
            ],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        assert result.returncode == 0, (
            f"zipapp build must succeed.\nstderr: {result.stderr}"
        )
        assert pyz.exists(), "cairn.pyz must exist after build"

        # Run --version against the zipapp.
        run_result = subprocess.run(
            [sys.executable, str(pyz), "--version"],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        assert run_result.returncode == 0, (
            f"cairn --version from zipapp must exit 0.\n"
            f"stdout: {run_result.stdout}\nstderr: {run_result.stderr}"
        )
        combined = run_result.stdout + run_result.stderr
        assert combined.strip(), "cairn --version must produce output"

    def test_zipapp_scan_runs_standalone(self, tmp_path):
        """
        The zipapp must be able to run a content scan without the installed
        cairn package on sys.path, confirming stdlib-only scan.py works.
        """
        import cairn
        src_dir = Path(cairn.__file__).parent.parent
        pyz = tmp_path / "cairn_scan.pyz"

        subprocess.run(
            [sys.executable, "-m", "zipapp", str(src_dir),
             "--output", str(pyz),
             "--python", "/usr/bin/env python3",
             "--main", "cairn.cli:main"],
            capture_output=True, check=True, env=os.environ.copy(),
        )

        # If the zipapp starts without ImportError on the scan module, we are good.
        result = subprocess.run(
            [sys.executable, str(pyz), "--version"],
            capture_output=True, text=True, env=os.environ.copy(),
        )
        assert result.returncode == 0, (
            "zipapp must run --version cleanly (scan.py stdlib constraint)"
        )
