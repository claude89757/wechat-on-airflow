from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGO_PATH = ROOT / "webapp/public/assets/zacks-logo.webp"


def test_supplied_logo_is_the_header_brand_and_browser_icon():
    index = (ROOT / "webapp/index.html").read_text(encoding="utf-8")
    styles = (ROOT / "webapp/src/brand-logo.css").read_text(encoding="utf-8")
    logo = LOGO_PATH.read_bytes()

    assert 'href="/assets/zacks-logo.webp"' in index
    assert 'rel="icon"' in index
    assert 'rel="preload"' in index
    assert 'href="/src/brand-logo.css"' in index
    assert 'url("/assets/zacks-logo.webp")' in styles
    assert "html body .brand-mark svg" in styles
    assert "opacity: 0" in styles

    assert logo[:4] == b"RIFF"
    assert logo[8:12] == b"WEBP"
    assert 3_000 <= len(logo) <= 20_000
