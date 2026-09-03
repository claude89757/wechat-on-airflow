from __future__ import annotations

from pathlib import Path


def main() -> int:
    path = Path("src/wechat_airflow/host_core/domain.py")
    text = path.read_text(encoding="utf-8")
    old = '''def weekdays_from_mask(value: object) -> list[int]:
    try:
        mask = int(value)
    except (TypeError, ValueError):
        mask = ALL_WEEKDAY_MASK
    if mask < 1 or mask > ALL_WEEKDAY_MASK:
        mask = ALL_WEEKDAY_MASK
    return [weekday for weekday in range(1, 8) if mask & (1 << (weekday - 1))]
'''
    new = '''def weekdays_from_mask(value: object) -> list[int]:
    mask = ALL_WEEKDAY_MASK
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        try:
            mask = int(value)
        except ValueError:
            mask = ALL_WEEKDAY_MASK
    if mask < 1 or mask > ALL_WEEKDAY_MASK:
        mask = ALL_WEEKDAY_MASK
    return [weekday for weekday in range(1, 8) if mask & (1 << (weekday - 1))]
'''
    if text.count(old) != 1:
        raise RuntimeError("unexpected weekdays_from_mask implementation")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
