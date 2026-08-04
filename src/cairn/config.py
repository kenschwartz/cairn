import os
import sys
from pathlib import Path

DEFAULT_ALLOWLIST = [
    "https://github.com/CFG-INNERSOURCE/",
    "git@github.com:CFG-INNERSOURCE/",
]


def get_allowlist():
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if not config_home:
        config_home = str(Path.home() / ".config")
    config_path = Path(config_home) / "cairn" / "config.toml"
    if not config_path.exists():
        return DEFAULT_ALLOWLIST[:]

    import tomllib
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        print(
            f"cairn: malformed config file {config_path}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    remote = data.get("remote")
    if remote is None:
        return DEFAULT_ALLOWLIST[:]
    if not isinstance(remote, dict):
        print(
            f"cairn: malformed config file {config_path}: [remote] must be a table",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    prefixes = remote.get("allowed_prefixes")
    if prefixes is None:
        return DEFAULT_ALLOWLIST[:]
    if not isinstance(prefixes, list) or not all(isinstance(p, str) for p in prefixes):
        print(
            f"cairn: malformed config file {config_path}: "
            "allowed_prefixes must be a list of strings",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    return prefixes[:]
