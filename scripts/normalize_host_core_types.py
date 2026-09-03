from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def update_domain() -> None:
    replace_exact(
        "src/wechat_airflow/host_core/domain.py",
        '''    weekdays = tuple(sorted({int(item) for item in value}))
    if not weekdays or any(item < 1 or item > 7 for item in weekdays):
        raise ValueError("星期选择无效")
    return weekdays
''',
        '''    parsed: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise ValueError("星期选择无效")
        try:
            parsed.add(int(item))
        except ValueError as exc:
            raise ValueError("星期选择无效") from exc
    weekdays = tuple(sorted(parsed))
    if not weekdays or any(item < 1 or item > 7 for item in weekdays):
        raise ValueError("星期选择无效")
    return weekdays
''',
    )


def update_migration() -> None:
    replace_exact(
        "src/wechat_airflow/host_core/migration.py",
        '''    if isinstance(value, (int, float)) or str(value).isdigit():
        number = int(value)
        if number > 10_000_000_000:
            number //= 1_000
        try:
            return datetime.fromtimestamp(number, UTC)
        except (OSError, OverflowError, ValueError):
            return default
''',
        '''    number: int | None = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = int(value)
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    if number is not None:
        if number > 10_000_000_000:
            number //= 1_000
        try:
            return datetime.fromtimestamp(number, UTC)
        except (OSError, OverflowError, ValueError):
            return default
''',
    )
    replace_exact(
        "src/wechat_airflow/host_core/migration.py",
        '''        response = session.get(
            f"{base_url.rstrip('/')}/api/internal/host-migration-export",
            params={"table": table, "cursor": cursor, "limit": 500},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
''',
        '''        params: dict[str, str | int] = {
            "table": table,
            "cursor": cursor,
            "limit": 500,
        }
        response = session.get(
            f"{base_url.rstrip('/')}/api/internal/host-migration-export",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
''',
    )


def update_api() -> None:
    replace_exact(
        "src/wechat_airflow/host_core/api.py",
        '''    for row in rows:
        code = decrypt_invite_code(row["encrypted_code"], settings.invite_pepper)
        status = (
''',
        '''    for row in rows:
        stored_code = decrypt_invite_code(row["encrypted_code"], settings.invite_pepper)
        status = (
''',
    )
    replace_exact(
        "src/wechat_airflow/host_core/api.py",
        '''                "code": code,
                "codeHint": row["code_hint"],
                "recoverable": bool(code),
''',
        '''                "code": stored_code,
                "codeHint": row["code_hint"],
                "recoverable": bool(stored_code),
''',
    )


def update_contracts() -> None:
    replace_exact(
        "config/active-components.yaml",
        "      - webapp_is_the_only_email_delivery_owner\n",
        "      - airflow_host_is_the_only_email_delivery_owner_after_cutover\n",
    )

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text(encoding="utf-8")
    if "## [0.7.0]" not in text:
        marker = "## Unreleased\n\n"
        if text.count(marker) != 1:
            raise RuntimeError("unexpected changelog structure")
        section = '''## [0.7.0] - 2026-09-04

### Added

- Add the PostgreSQL-backed Airflow-host subscription, observation, notification,
  migration, and delivery runtime, including an exact-commit API service and a
  leased notification worker.
- Add a protected shadow-migration and cutover workflow that transfers existing
  D1 state and Tencent SES configuration without exposing plaintext credentials
  to GitHub or sending synthetic notifications.
- Add a stateless Cloudflare edge gateway that serves the Web assets while
  proxying API calls to the host after cutover.

### Changed

- Make PostgreSQL schema `zacks` the authoritative durable store for identities,
  subscriptions, event deduplication, quotas, email Outboxes, and provider state.
- Move subscriber email matching, Tencent SES delivery, retry, and reconciliation
  from Cloudflare to the Airflow host.
- Move the venue-level WeChat subscription gate from D1 to local PostgreSQL while
  retaining the existing Airflow-to-Android delivery path.
- Reduce Cloudflare to DNS/TLS/WAF, static assets, a stateless API proxy, and
  Tunnel ingress; retain D1 read-only for the rollback window.
- Preserve every active venue polling cadence and isolate existing email and
  WeChat delivery from Cloudflare D1 availability.

'''
        changelog.write_text(text.replace(marker, marker + section, 1), encoding="utf-8")


def main() -> int:
    update_domain()
    update_migration()
    update_api()
    update_contracts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
