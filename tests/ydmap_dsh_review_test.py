from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ydmap_dsh_review as review  # noqa: E402


def test_service_metadata_does_not_return_command_arguments(monkeypatch):
    values = iter(
        [
            "/home/example/dsh-workspace",
            "{ path=/opt/node/bin/node ; argv[]=/opt/node/bin/node /opt/harness/apps/cli/lib/bin.js --token=never-export-this ; }",
        ]
    )
    monkeypatch.setattr(
        review.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=next(values))
    )
    monkeypatch.setattr(review.shutil, "which", lambda name: None)
    roots, nodes = review.service_roots()
    assert Path("/opt/harness/apps/cli") in roots
    assert nodes == ["/opt/node/bin/node"]
    assert "never-export" not in str((roots, nodes))


def test_only_named_installed_package_entry_is_used(tmp_path, monkeypatch):
    package = tmp_path / "apps/cli"
    (package / "lib").mkdir(parents=True)
    (package / "lib/bin.js").write_text("// installed public launcher")
    (package / "package.json").write_text(
        json.dumps({"name": "@deepseek-ai/dsh", "version": "test", "bin": {"dsh": "lib/bin.js"}})
    )
    monkeypatch.setattr(review, "service_roots", lambda: ([tmp_path], ["/usr/bin/node"]))
    monkeypatch.setattr(review.shutil, "which", lambda name: None)
    report = {}
    assert review.installed_command(report) == ["/usr/bin/node", str(package / "lib/bin.js")]
    assert report["installedVersion"] == "test"


def test_manifest_cannot_escape_its_package(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "@deepseek-ai/dsh", "bin": {"dsh": "../other.js"}})
    )
    monkeypatch.setattr(review, "service_roots", lambda: ([tmp_path], ["/usr/bin/node"]))
    monkeypatch.setattr(review.shutil, "which", lambda name: None)
    assert review.installed_command({}) is None


def test_scoped_npm_package_launcher_is_discovered_without_flags(monkeypatch):
    values = iter(
        [
            "/home/example/dsh-workspace",
            "{ path=/opt/node-v22/bin/node ; argv[]=/opt/node-v22/bin/node /opt/apps/node_modules/@deepseek-ai/dsh/lib/bin.js --secret=must-not-escape ; ignore_errors=no ; }",
        ]
    )
    monkeypatch.setattr(
        review.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=next(values))
    )
    monkeypatch.setattr(review.shutil, "which", lambda name: None)
    roots, nodes = review.service_roots()
    assert Path("/opt/apps/node_modules/@deepseek-ai/dsh") in roots
    assert Path("/opt/node-v22/lib/node_modules/@deepseek-ai/dsh") in roots
    assert nodes == ["/opt/node-v22/bin/node"]
    assert "must-not-escape" not in str(roots)
