"""Prevent a Host Core runtime patch from being shipped as an Airflow-only update."""

from __future__ import annotations

import argparse

from release_plan import diff_files, previous_release_commit, resolve_commit


def requires_host_core(paths: list[str]) -> bool:
    return any(path.startswith("src/wechat_airflow/host_core/") for path in paths)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True)
    args = parser.parse_args()
    target = resolve_commit("HEAD")
    if (
        requires_host_core(diff_files(previous_release_commit(target), target))
        and args.scope != "all"
    ):
        parser.error("Host Core changes require scope=all sender=true and full business acceptance")


if __name__ == "__main__":
    main()
