from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_venue_section_avoids_duplicate_refresh_nudges() -> None:
    main = (ROOT / "webapp/src/main.tsx").read_text(encoding="utf-8")
    prototype = (ROOT / "webapp/src/Prototype.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "webapp/src/venue-section-refresh.css").read_text(encoding="utf-8")

    assert 'import "./venue-section-refresh.css";' in main
    assert ".venue-section .section-heading > div > p" in styles
    assert ".venue-section .section-heading > div::after" in styles
    assert 'content: "点按卡片快速创建提醒";' in styles
    assert ".venue-section .section-heading > span" in styles
    assert styles.count("display: none;") == 2
    assert 'aria-label="获取最新状态"' in prototype
    assert "onClick={() => void refresh(true)}" in prototype
