"""Keep the exact-version Host Core consumer and Android Sender in one release."""

from __future__ import annotations

import argparse

from release_plan import diff_files, previous_release_commit, resolve_commit

# The consumer compares Sender deploymentCommit with its own commit before every
# send. A healthy Sender-only upgrade therefore blocks all natural notifications.
COUPLED_PREFIXES = (
    "src/wechat_airflow/host_core/",
    "sender_agent/",
    "wechat_sender/",
    "docker/sender/",
)
COUPLED_FILES = {
    "deploy/systemd/wechat-sender.service",
    "docker-compose.sender.yml",
    "scripts/install_wechat_sender.sh",
    "scripts/deploy_wechat_sender.py",
    "scripts/preserve_sender_legacy_patch.py",
}


def requires_host_core(paths: list[str]) -> bool:
    return any(path.startswith(COUPLED_PREFIXES) or path in COUPLED_FILES for path in paths)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True)
    args = parser.parse_args()
    target = resolve_commit("HEAD")
    if (
        requires_host_core(diff_files(previous_release_commit(target), target))
        and args.scope != "all"
    ):
        parser.error(
            "Host Core or Sender changes require scope=all sender=true and full business acceptance"
        )


if __name__ == "__main__":
    main()
