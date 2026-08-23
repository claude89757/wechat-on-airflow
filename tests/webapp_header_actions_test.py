from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_footer_actions_move_into_accessible_header_menu():
    source = (ROOT / "webapp/src/Prototype.tsx").read_text(encoding="utf-8")

    assert 'aria-label="更多功能"' in source
    assert "<DropdownMenu.Root>" in source
    assert 'onSelect={() => openPanel("subscriptions")}' in source
    assert 'onSelect={() => openPanel("community")}' in source
    assert 'onSelect={() => openPanel("admin")}' in source
    assert 'className="subscriptions-link"' not in source


def test_more_menu_pointer_transfer_cannot_start_mobile_scroll_drag():
    index = (ROOT / "webapp/index.html").read_text(encoding="utf-8")
    guard = (ROOT / "webapp/src/menu-scroll-drag-guard.ts").read_text(encoding="utf-8")

    guard_entry = 'src="/src/menu-scroll-drag-guard.ts"'
    app_entry = 'src="/src/main.tsx"'
    assert guard_entry in index
    assert index.index(guard_entry) < index.index(app_entry)
    assert '[aria-haspopup="menu"]' in guard
    assert 'const CUSTOM_SCROLL_SELECTOR = ".mobile-scroll"' in guard
    assert 'document.addEventListener("pointerdown"' in guard
    assert "capture: true" in guard
    assert 'trigger.dataset.scrollDrag = "ignore"' in guard


def test_coffee_entry_uses_compact_copy_and_keeps_full_accessible_name():
    source = (ROOT / "webapp/src/Prototype.tsx").read_text(encoding="utf-8")
    index = (ROOT / "webapp/index.html").read_text(encoding="utf-8")
    styles = (ROOT / "webapp/src/header-menu.css").read_text(encoding="utf-8")

    assert '<span aria-hidden="true">☕</span>' in source
    assert "<span>支持作者</span>" in source
    assert 'aria-label="请作者喝咖啡，支持项目维护"' in source
    assert 'href="/src/header-menu.css"' in index
    assert ".more-menu-item[data-highlighted]" in styles
