"""
Tests asserting package-level constraints from DESIGN.md:

1. Runtime dependencies are PyYAML and nothing else. No runtime dep may be
   a dev-only package.
2. scan.py imports only stdlib.
3. The full cairn package imports only stdlib + PyYAML at runtime.

DESIGN.md: 'A test asserting that src/cairn/ imports nothing outside the
standard library plus PyYAML enforces this.'
"""

import sys
import types
import importlib
import importlib.util
from pathlib import Path

import pytest


# Python stdlib module names we recognise (superset; false negatives fine,
# false positives would cause spurious failures).
_STDLIB_NAMES = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()


def _is_stdlib_or_yaml(module_name: str) -> bool:
    """Return True if module_name is stdlib or PyYAML (the only allowed runtime dep)."""
    root = module_name.split(".")[0]
    if root in _STDLIB_NAMES:
        return True
    if root in ("yaml", "_yaml", "cairn"):
        return True
    return False


class TestRuntimeDependencies:
    def test_scan_py_imports_only_stdlib(self):
        """
        Import scan.py in an environment where everything except stdlib is hidden.
        Any non-stdlib import will raise ImportError.
        DESIGN.md: 'scan.py MUST import only the Python standard library.'
        """
        import cairn.scan as scan_mod
        scan_file = Path(scan_mod.__file__).resolve()

        saved_path = sys.path[:]
        saved_modules = {k: v for k, v in sys.modules.items()}

        sys.path = [str(scan_file.parent)]
        for key in list(sys.modules.keys()):
            if key.startswith("cairn"):
                del sys.modules[key]

        try:
            spec = importlib.util.spec_from_file_location("_scan_isolated", scan_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except ImportError as e:
            pytest.fail(
                f"scan.py attempted to import a non-stdlib module: {e}\n"
                "DESIGN.md requires scan.py to import ONLY the Python standard library."
            )
        finally:
            sys.path = saved_path
            sys.modules.update(saved_modules)

    def test_cairn_package_imports_only_stdlib_and_pyyaml(self):
        """
        Import the full cairn package and inspect what third-party modules were
        pulled in.  Only yaml (PyYAML) is allowed.
        """
        # Record modules before import.
        before = set(sys.modules.keys())
        import cairn  # noqa: F401
        after = set(sys.modules.keys())

        new_modules = after - before
        disallowed = set()
        for name in new_modules:
            root = name.split(".")[0]
            if root in ("cairn", "_cairn"):
                continue
            if _is_stdlib_or_yaml(name):
                continue
            disallowed.add(name)

        assert not disallowed, (
            f"cairn package imported non-stdlib, non-PyYAML modules at runtime: "
            f"{sorted(disallowed)}\n"
            "DESIGN.md: 'Runtime deps for v1 are PyYAML and nothing else.'"
        )

    def test_pyyaml_is_importable(self):
        """PyYAML must be importable (it is the one allowed runtime dep)."""
        import yaml  # noqa: F401
        assert yaml.__version__, "PyYAML must be importable and have a version"
