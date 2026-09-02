from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_worker_persists_and_matches_subscription_weekdays():
    worker = (ROOT / "webapp/cloudflare/index.ts").read_text(encoding="utf-8")

    assert "s.weekday_mask" in worker
    assert "weekdayMaskFromDays(input.weekdays)" in worker
    assert "weekdays: weekdaysFromMask(subscription.weekday_mask)" in worker
    assert "slotMatchesWeekday(slot, subscription.weekday_mask)" in worker
    assert "相同场地、星期和时间条件" in worker


def test_public_venue_popularity_uses_unique_followers_and_stable_order():
    worker = (ROOT / "webapp/cloudflare/index.ts").read_text(encoding="utf-8")
    ui = (ROOT / "webapp/src/Prototype.tsx").read_text(encoding="utf-8")

    assert "COUNT(DISTINCT s.email)" in worker
    assert "ORDER BY subscriber_count DESC" in worker
    assert "点按卡片快速创建提醒 · 页面数据由用户手动刷新" in ui
    assert "点击顶部按钮获取最新数据" in ui
    assert "right.subscriberCount - left.subscriberCount" in ui


def test_subscription_success_and_email_guidance_are_accessible():
    ui = (ROOT / "webapp/src/Prototype.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "webapp/src/prototype.css").read_text(encoding="utf-8")

    assert 'data-testid="subscription-celebration"' in ui
    assert 'aria-live="polite" id="subscription-summary"' in ui
    assert 'className="email-delivery-tip" role="note"' in ui
    assert "不是垃圾邮件" in ui
    assert "pointer-events: none" in styles
    assert "prefers-reduced-motion: reduce" in styles
