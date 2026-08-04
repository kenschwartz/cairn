"""
Unit tests for cairn.cli argument parsing and dispatch.

The integration suite drives the real `cairn` executable; these tests pin the
parser contract itself: which subcommand runs, what defaults land in the
Namespace, and what the process exit code is. Command bodies are stubbed so a
parsing regression cannot hide behind a working command.

Hermeticity: no filesystem I/O, no git, no subprocess.
"""

import pytest

from cairn import cli


@pytest.fixture()
def calls(monkeypatch):
    """Replace every command entry point with a recorder."""
    recorded = {}

    def recorder(name):
        def _run(args):
            recorded["command"] = name
            recorded["args"] = args
            return 0

        return _run

    for name in ("init", "doctor", "new"):
        monkeypatch.setattr(cli, f"run_{name}", recorder(name))
    return recorded


def run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["cairn"] + argv)
    return cli.main()


class TestDispatch:
    @pytest.mark.parametrize("command", ["init", "doctor", "new"])
    def test_subcommand_dispatches_to_its_handler(self, monkeypatch, calls, command):
        run(monkeypatch, [command, "x"] if command == "new" else [command])
        assert calls["command"] == command

    def test_handler_return_code_is_propagated(self, monkeypatch):
        monkeypatch.setattr(cli, "run_doctor", lambda args: 3)
        assert run(monkeypatch, ["doctor"]) == 3

    def test_no_subcommand_prints_help_and_fails(self, monkeypatch, calls, capsys):
        assert run(monkeypatch, []) == 1
        assert "usage: cairn" in capsys.readouterr().out
        assert calls == {}

    def test_unknown_subcommand_exits_nonzero(self, monkeypatch, calls):
        with pytest.raises(SystemExit) as exc:
            run(monkeypatch, ["bogus"])
        assert exc.value.code != 0

    def test_version_flag_exits_zero_with_version(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run(monkeypatch, ["--version"])
        assert exc.value.code == 0
        assert capsys.readouterr().out.strip() == "cairn 1.0.0"


class TestInitParsing:
    def test_path_defaults_to_cwd(self, monkeypatch, calls):
        run(monkeypatch, ["init"])
        assert calls["args"].path == "."

    def test_explicit_path(self, monkeypatch, calls):
        run(monkeypatch, ["init", "/tmp/vault"])
        assert calls["args"].path == "/tmp/vault"


class TestDoctorParsing:
    def test_fix_defaults_off(self, monkeypatch, calls):
        run(monkeypatch, ["doctor"])
        assert calls["args"].fix is False

    def test_fix_flag(self, monkeypatch, calls):
        run(monkeypatch, ["doctor", "--fix"])
        assert calls["args"].fix is True

    def test_scan_history_defaults_to_20(self, monkeypatch, calls):
        run(monkeypatch, ["doctor"])
        assert calls["args"].scan_history == 20

    def test_scan_history_is_an_int(self, monkeypatch, calls):
        run(monkeypatch, ["doctor", "--scan-history", "5"])
        assert calls["args"].scan_history == 5

    def test_non_integer_scan_history_is_rejected(self, monkeypatch, calls):
        with pytest.raises(SystemExit):
            run(monkeypatch, ["doctor", "--scan-history", "deep"])


class TestNewParsing:
    def test_title_is_positional(self, monkeypatch, calls):
        run(monkeypatch, ["new", "Quarterly review"])
        assert calls["args"].title == "Quarterly review"

    def test_missing_title_reaches_the_command_as_none(self, monkeypatch, calls):
        run(monkeypatch, ["new"])
        assert calls["args"].title is None

    def test_type_defaults_to_note(self, monkeypatch, calls):
        run(monkeypatch, ["new", "T"])
        assert calls["args"].type == "note"

    def test_type_is_not_validated_by_the_parser(self, monkeypatch, calls):
        run(monkeypatch, ["new", "T", "--type", "bogus"])
        assert calls["args"].type == "bogus"

    def test_tag_defaults_to_none(self, monkeypatch, calls):
        run(monkeypatch, ["new", "T"])
        assert calls["args"].tag is None

    def test_tag_is_repeatable_and_ordered(self, monkeypatch, calls):
        run(monkeypatch, ["new", "T", "--tag", "work", "--tag", "ops"])
        assert calls["args"].tag == ["work", "ops"]

    def test_project_defaults_to_empty_string(self, monkeypatch, calls):
        run(monkeypatch, ["new", "T"])
        assert calls["args"].project == ""

    def test_project_explicit(self, monkeypatch, calls):
        run(monkeypatch, ["new", "T", "--project", "cairn"])
        assert calls["args"].project == "cairn"
