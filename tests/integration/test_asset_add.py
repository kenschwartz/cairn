"""
Gating tests for `cairn asset add` (Phase 5).

Per docs/decisions.md "cairn asset add" + DESIGN:564-639:
- `cairn asset add <path> [--note <path>] [--large] [--source-url <url>]`
- Normal (<=1 MB): copy into assets/ (tracked), commit.
- >1 MB without --large: refuse (the Phase-1 pre-commit hook enforces a 1 MB cap
  on assets/, so --large cannot commit there). --large instead copies into
  gitignored assets/local/ and writes a tracked assets/local.manifest.json entry
  (sha256, size, added, referenced_by); the manifest is committed, the binary is
  not. The hook verifies the manifest sha against the on-disk file, so a
  successful --large commit PROVES the recorded sha is correct.
- --note: append a relative markdown link to that note; --source-url sets the
  note's source_url frontmatter.
"""

import json
import os
import subprocess
import hashlib
from pathlib import Path

from cairn.frontmatter import write_frontmatter, read_frontmatter


def _run(vault, args):
    return subprocess.run(["cairn", "asset", "add"] + args, cwd=str(vault),
                          capture_output=True, text=True, env=os.environ.copy())


def _git(args, vault):
    return subprocess.run(["git"] + args, cwd=str(vault),
                          capture_output=True, text=True, env=os.environ.copy())


FM = {
    "id": "z", "title": "T", "type": "note", "status": "active", "project": "",
    "tags": ["x"], "created": "2026-08-09", "updated": "2026-08-09",
    "cairn_version": 1, "moc": "", "source": "", "source_url": "",
}


def _seed_note(vault, name="n.md", title="Note"):
    (vault / "notes" / name).write_text(write_frontmatter(dict(FM, id="n1", title=title)) + "body\n")
    _git(["add", "notes"], vault)
    _git(["commit", "-m", "seed"], vault)
    return vault / "notes" / name


class TestAssetAddNormal:
    def test_copies_small_file_and_commits(self, tmp_vault, tmp_path):
        src = tmp_path / "small.txt"
        src.write_text("hello asset\n")
        r = _run(tmp_vault, [str(src)])
        assert r.returncode == 0, r.stderr
        dest = tmp_vault / "assets" / "small.txt"
        assert dest.exists()
        assert dest.read_text() == "hello asset\n"
        # committed
        show = _git(["show", "--name-only", "HEAD"], tmp_vault).stdout
        assert "assets/small.txt" in show

    def test_note_appends_link_and_source_url(self, tmp_vault, tmp_path):
        note = _seed_note(tmp_vault)
        src = tmp_path / "doc.txt"
        src.write_text("doc body\n")
        r = _run(tmp_vault, [str(src), "--note", str(note.relative_to(tmp_vault)),
                             "--source-url", "https://example.com/source"])
        assert r.returncode == 0, r.stderr
        fm, body = read_frontmatter(note)
        assert "assets/doc.txt" in body
        assert fm["source_url"] == "https://example.com/source"


class TestAssetAddLarge:
    def test_large_without_flag_refuses(self, tmp_vault, tmp_path):
        big = tmp_path / "big.bin"
        big.write_bytes(b"0" * (2 * 1024 * 1024))  # 2 MB
        r = _run(tmp_vault, [str(big)])
        assert r.returncode != 0, ">1MB without --large must be refused"
        assert not (tmp_vault / "assets" / "big.bin").exists()

    def test_large_with_flag_uses_local_and_manifest(self, tmp_vault, tmp_path):
        big = tmp_path / "big.bin"
        data = b"0" * (2 * 1024 * 1024)
        big.write_bytes(data)
        r = _run(tmp_vault, [str(big), "--large"])
        assert r.returncode == 0, r.stderr
        # binary is in gitignored assets/local/, NOT in tracked assets/
        assert (tmp_vault / "assets" / "local" / "big.bin").exists()
        assert not (tmp_vault / "assets" / "big.bin").exists()
        # manifest committed with a correct sha256 entry
        manifest_path = tmp_vault / "assets" / "local.manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        entries = manifest["entries"]
        assert any(e["path"] == "assets/local/big.bin" for e in entries)
        entry = next(e for e in entries if e["path"] == "assets/local/big.bin")
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["size_bytes"] == len(data)
        # the manifest (not the binary) is committed
        show = _git(["show", "--name-only", "HEAD"], tmp_vault).stdout
        assert "assets/local.manifest.json" in show
        assert "assets/local/big.bin" not in show  # gitignored

    def test_large_manifest_sha_is_hook_verified(self, tmp_vault, tmp_path):
        # A successful --large commit means the pre-commit hook verified the
        # manifest sha against the on-disk file and passed. Corrupting the file
        # after the fact, then committing anything, must then FAIL the hook.
        big = tmp_path / "big.bin"
        big.write_bytes(b"0" * (2 * 1024 * 1024))
        _run(tmp_vault, [str(big), "--large"])
        # corrupt the on-disk local file (sha no longer matches manifest)
        (tmp_vault / "assets" / "local" / "big.bin").write_bytes(b"tampered")
        _git(["add", "notes"], tmp_vault)  # stage an unrelated change
        (tmp_vault / "notes" / "probe.md").write_text(
            write_frontmatter(dict(FM, id="p1", title="Probe")) + "x\n")
        _git(["add", "notes/probe.md"], tmp_vault)
        commit = _git(["commit", "-m", "probe"], tmp_vault)
        assert commit.returncode != 0, "hook must fail when a manifest sha no longer matches the file"
