from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def block(value: str) -> str:
    return dedent(value).lstrip("\n")


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{path}: expected {expected} matches, found {count}: {old!r}")
    file.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "webapp/cloudflare/index.ts",
    block(
        '''
        import {
          deliveryLimitForTier,
          normalizeDeliveryTier,
          remainingDailyDeliveries,
          type DeliveryTier,
        } from "./delivery-tiers";
        '''
    ),
    block(
        '''
        import {
          deliveryLimitForTier,
          deliveryTierLimits,
          normalizeDeliveryTier,
          remainingDailyDeliveries,
          type DeliveryTier,
        } from "./delivery-tiers";
        '''
    ),
)
replace_once(
    "webapp/cloudflare/index.ts",
    "  const identityDailyLimit = deliveryLimitForTier(env, identityTier);",
    "  const tierLimits = deliveryTierLimits(env);\n  const identityDailyLimit = tierLimits[identityTier];",
)
replace_once(
    "webapp/cloudflare/index.ts",
    "    venues,\n    identity: {",
    "    deliveryTiers: tierLimits,\n    venues,\n    identity: {",
)

replace_once(
    "webapp/src/api.ts",
    "  venues: VenueStatus[];",
    "  deliveryTiers: { standard: number; priority: number };\n  venues: VenueStatus[];",
)
replace_once(
    "webapp/src/api.ts",
    block(
        '''
          metrics: {
            activeSubscriptions: 128,
            remindersToday: 6,
            healthyVenues: 7,
            totalVenues: 7,
          },
          venues: [
        '''
    ),
    block(
        '''
          metrics: {
            activeSubscriptions: 128,
            remindersToday: 6,
            healthyVenues: 7,
            totalVenues: 7,
          },
          deliveryTiers: { standard: 30, priority: 100 },
          venues: [
        '''
    ),
)
replace_once(
    "webapp/src/api.ts",
    block(
        '''
          metrics: {
            activeSubscriptions: 0,
            remindersToday: 0,
            healthyVenues: 0,
            totalVenues: 7,
          },
          venues: FALLBACK_DASHBOARD.venues.map((venue) => ({
        '''
    ),
    block(
        '''
          metrics: {
            activeSubscriptions: 0,
            remindersToday: 0,
            healthyVenues: 0,
            totalVenues: 7,
          },
          deliveryTiers: { standard: 30, priority: 100 },
          venues: FALLBACK_DASHBOARD.venues.map((venue) => ({
        '''
    ),
)
replace_all("webapp/src/api.ts", "    dailyLimit: 3,", "    dailyLimit: 30,", 2)
replace_all("webapp/src/api.ts", "    remainingToday: 3,", "    remainingToday: 30,", 2)

replace_once(
    "webapp/src/Prototype.tsx",
    block(
        '''
                            <small>
                              今日已发送 {dashboard.identity.remindersToday}/{dashboard.identity.dailyLimit} 封
                            </small>
        '''
    ),
    block(
        '''
                            <small>
                              今日 {dashboard.identity.remindersToday}/{dashboard.identity.dailyLimit} 封
                              · 还可发送 {dashboard.identity.remainingToday} 封
                            </small>
        '''
    ),
)
replace_once(
    "webapp/src/Prototype.tsx",
    block(
        '''
                        {dashboard.identity.tier === "priority" ? (
                          <span className="tier-enabled">优先队列已开启</span>
                        ) : (
                          <button type="button" onClick={() => openPanel("priority")}>
                            输入邀请码
                          </button>
                        )}
        '''
    ),
    block(
        '''
                        <button
                          type="button"
                          className={dashboard.identity.tier === "priority" ? "tier-enabled" : undefined}
                          onClick={() => openPanel("priority")}
                        >
                          {dashboard.identity.tier === "priority" ? "查看规则" : "输入邀请码"}
                        </button>
        '''
    ),
)
replace_once(
    "webapp/src/Prototype.tsx",
    block(
        '''
                    <div className="help-row">
                      <span>3</span>
                      <div><strong>命中后发邮件</strong><p>只有出现符合条件的场地位才会通知，不会重复轰炸。</p></div>
                    </div>
        '''
    ),
    block(
        '''
                    <div className="help-row">
                      <span>3</span>
                      <div><strong>命中后发邮件</strong><p>同一轮的多个场地和时段会合并为一封摘要邮件。</p></div>
                    </div>
                    <div className="help-row">
                      <span>4</span>
                      <div>
                        <strong>每日邮件额度</strong>
                        <p>
                          普通用户每天最多 {dashboard.deliveryTiers.standard} 封，优先用户最多
                          {dashboard.deliveryTiers.priority} 封；按深圳时间 00:00 重置。
                        </p>
                      </div>
                    </div>
        '''
    ),
)
replace_once(
    "webapp/src/Prototype.tsx",
    block(
        '''
                      <article>
                        <span>普通用户</span>
                        <strong>默认 3 封/天</strong>
                        <p>适合日常关注；达到上限后，当天后续场地提醒不再补发。</p>
                      </article>
                      <article className="featured">
                        <span><StarIcon size={17} weight="fill" />优先用户</span>
                        <strong>默认 12 封/天</strong>
                        <p>更高提醒额度，并在系统全局邮件额度紧张时优先处理。</p>
                      </article>
        '''
    ),
    block(
        '''
                      <article>
                        <span>普通用户</span>
                        <strong>{dashboard.deliveryTiers.standard} 封/天</strong>
                        <p>邮箱验证后自动获得，适合日常关注场地空位。</p>
                      </article>
                      <article className="featured">
                        <span><StarIcon size={17} weight="fill" />优先用户</span>
                        <strong>{dashboard.deliveryTiers.priority} 封/天</strong>
                        <p>使用一次性趣味口令升级，全局邮件额度紧张时优先处理。</p>
                      </article>
        '''
    ),
)
replace_once(
    "webapp/src/Prototype.tsx",
    block(
        '''
                    </div>

                    {receipt ? (
                      dashboard.identity.tier === "priority" ? (
        '''
    ),
    block(
        '''
                    </div>

                    <ul className="quota-rules">
                      <li><strong>每天重置：</strong>按深圳时间 00:00 重新计算。</li>
                      <li><strong>摘要计数：</strong>一封邮件可合并多个场地和时段，只计 1 封。</li>
                      <li><strong>达到上限：</strong>当天后续空位邮件不发送，也不会隔天补发旧空位。</li>
                      <li><strong>不计额度：</strong>邮箱验证码和微信消息不受档位限制。</li>
                    </ul>

                    {receipt ? (
                      dashboard.identity.tier === "priority" ? (
        '''
    ),
)
replace_once(
    "webapp/src/Prototype.tsx",
    '        snap={panel === "create" ? 0.86 : panel === "priority" ? 0.66 : 0.72}',
    '        snap={panel === "create" ? 0.86 : panel === "priority" ? 0.82 : 0.72}',
)
replace_once("webapp/src/Prototype.tsx", "                      maxLength={40}", "                      maxLength={32}")
replace_once(
    "webapp/src/Prototype.tsx",
    '                      placeholder="ZACKS-XXXXXXX-XXXXXXX-XXXXXXX-XXXXXXX"',
    '                      placeholder="ACE-SUNNY-PANDA-7K9P2Q"',
)
replace_once(
    "webapp/src/Prototype.tsx",
    block(
        '''
                          <p className="verification-note">
                            邀请码仅可使用一次。验证成功后，优先档位会跟随此邮箱，
                            更换浏览器重新验证邮箱后仍然有效。
                          </p>
        '''
    ),
    block(
        '''
                          <p className="verification-note">
                            这是一个短而有趣的一次性口令，例如
                            <code className="invite-example">ACE-SUNNY-PANDA-7K9P2Q</code>。
                            不区分大小写，空格或连字符都可以；升级后优先档位会跟随此邮箱。
                          </p>
        '''
    ),
)
replace_once(
    "webapp/src/Prototype.tsx",
    '                            disabled={formBusy || inviteCode.replace(/[^A-Z0-9]/gi, "").length !== 33}',
    '                            disabled={formBusy || inviteCode.trim().length < 12}',
)

css_path = Path("webapp/src/prototype.css")
css = css_path.read_text(encoding="utf-8")
if ".quota-rules {" in css:
    raise RuntimeError("webapp/src/prototype.css: quota rule styles already exist")
css_path.write_text(
    css
    + block(
        '''

        .quota-rules {
          display: grid;
          gap: 9px;
          margin: 0;
          padding: 14px 16px;
          border: 1px solid rgba(42, 112, 105, 0.12);
          border-radius: 16px;
          background: #f7fbfa;
          color: #61736f;
          font-size: 12px;
          line-height: 1.55;
          list-style: none;
        }

        .quota-rules li {
          position: relative;
          padding-left: 18px;
        }

        .quota-rules li::before {
          position: absolute;
          top: 0;
          left: 0;
          color: var(--teal);
          content: "✓";
          font-weight: 800;
        }

        .quota-rules strong {
          color: #244c47;
        }

        .invite-example {
          display: inline-block;
          margin: 0 4px;
          padding: 2px 5px;
          border-radius: 5px;
          background: #edf6f3;
          color: #236b63;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          font-size: 10px;
          font-weight: 700;
          overflow-wrap: anywhere;
        }
        '''
    ),
    encoding="utf-8",
)

replace_once(
    "tests/webapp_delivery_tiers_migration_test.py",
    "        for index in range(2):",
    "        for index in range(29):",
)
replace_once(
    "tests/webapp_delivery_tiers_migration_test.py",
    "                    3,\n                ),\n            )\n            return result.rowcount",
    "                    30,\n                ),\n            )\n            return result.rowcount",
)

replace_once(
    "ARCHITECTURE.md",
    block(
        '''
        weather gate and before Tencent SES delivery. Standard recipients receive up to
        three digest emails per Shanghai calendar day; priority recipients receive up
        to twelve and are processed first when the global daily provider budget is
        constrained. Both values are Worker vars.
        '''
    ),
    block(
        '''
        weather gate and before Tencent SES delivery. Standard recipients receive up to
        30 digest emails per Shanghai calendar day; priority recipients receive up to
        100 and are processed first when the global daily provider budget is
        constrained. Both values are Worker vars and are returned to the Web client so
        visible quota copy matches backend enforcement.
        '''
    ),
)
replace_once(
    "ARCHITECTURE.md",
    block(
        '''
        Priority status is keyed by normalized verified email. A protected internal API
        creates high-entropy, one-time, expiring invite codes and returns plaintext only
        once. D1 stores only an HMAC-SHA-256 code hash. Redemption requires a valid
        browser receipt and is rate-limited by both verified email and hashed IP.
        '''
    ),
    block(
        '''
        Priority status is keyed by normalized verified email. A protected internal API
        creates short, memorable, one-time invite phrases from independently random
        word segments plus an ambiguity-free random suffix, and returns plaintext only
        once. D1 stores only an HMAC-SHA-256 code hash. Redemption requires a valid
        browser receipt and is rate-limited by both verified email and hashed IP.
        '''
    ),
)

replace_once(
    "webapp/AGENTS.md",
    block(
        '''
        - Subscriber reminder email uses two delivery tiers: standard users receive at
          most 3 digest deliveries per Shanghai calendar day; priority users receive at
          most 12 and are ordered first when the global provider budget is constrained.
          Verification email is never capped. Over-cap venue reminders are suppressed,
          not deferred, because availability may become stale.
        - Priority status belongs to the verified normalized email. Users redeem a
          cryptographically random, one-time, expiring invite code; the raw code is
          returned only at creation time and only its HMAC hash is stored.
        '''
    ),
    block(
        '''
        - Subscriber reminder email uses two delivery tiers: standard users receive at
          most 30 digest deliveries per Shanghai calendar day; priority users receive
          at most 100 and are ordered first when the global provider budget is
          constrained. Verification email is never capped. Over-cap venue reminders
          are suppressed, not deferred, because availability may become stale. The Web
          UI must show both limits, the signed-in identity's sent and remaining counts,
          the Shanghai-day reset, digest counting, non-replay behavior, and exclusions.
        - Priority status belongs to the verified normalized email. Users redeem a
          short, memorable, one-time invite phrase such as `ACE-SUNNY-PANDA-7K9P2Q`;
          the raw phrase is returned only at creation time and only its HMAC hash is
          stored.
        '''
    ),
)

replace_once(
    "docs/adr/0010-tiered-subscriber-email-and-invites.md",
    block(
        '''
        - Start with 3 deliveries per day for standard users and 12 for priority users.
          Both are configuration values and should be reviewed from delivery,
          suppression, complaint, and engagement data.
        '''
    ),
    block(
        '''
        - Start with 30 deliveries per day for standard users and 100 for priority users.
          Both are configuration values, are returned to the Web client for transparent
          display, and should be reviewed from delivery, suppression, complaint, and
          engagement data.
        '''
    ),
)
replace_once(
    "docs/adr/0010-tiered-subscriber-email-and-invites.md",
    block(
        '''
        - Provision one-time expiring invite codes through a separately authenticated
          internal endpoint. Generate at least 128 bits of CSPRNG entropy, return
          plaintext once, and store only an HMAC-SHA-256 hash protected by a Worker
          secret.
        '''
    ),
    block(
        '''
        - Provision one-time expiring invite phrases through a separately authenticated
          internal endpoint. Generate two independently random, human-readable word
          segments plus a six-character ambiguity-free random suffix, return plaintext
          once, and store only an HMAC-SHA-256 hash protected by a Worker secret. This
          shorter code is not an authentication session; verified-email and hashed-IP
          rate limits remain mandatory defenses against online guessing.
        '''
    ),
)

replace_once(
    "docs/runbooks/webapp-deployment.md",
    "- standard user: `STANDARD_DAILY_EMAIL_LIMIT=3`",
    "- standard user: `STANDARD_DAILY_EMAIL_LIMIT=30`",
)
replace_once(
    "docs/runbooks/webapp-deployment.md",
    "- priority user: `PRIORITY_DAILY_EMAIL_LIMIT=12`",
    "- priority user: `PRIORITY_DAILY_EMAIL_LIMIT=100`",
)
replace_once(
    "docs/runbooks/webapp-deployment.md",
    block(
        '''
        Each code contains 140 bits of cryptographic randomness, expires, and can be
        redeemed once. A verified user redeems it from the Web UI.
        '''
    ),
    block(
        '''
        Each code is a short memorable phrase such as
        `ACE-SUNNY-PANDA-7K9P2Q`: two CSPRNG-selected word segments plus a six-character
        ambiguity-free random suffix. It expires and can be redeemed once. A verified
        user redeems it from the Web UI.
        '''
    ),
)
replace_once(
    "docs/runbooks/webapp-deployment.md",
    "- the fourth standard digest in one Shanghai day is suppressed;",
    "- the thirty-first standard digest in one Shanghai day is suppressed;",
)
replace_once(
    "docs/runbooks/webapp-deployment.md",
    "- a priority identity can receive up to twelve digests;",
    "- a priority identity can receive up to one hundred digests;",
)
replace_once(
    "docs/runbooks/webapp-deployment.md",
    block(
        '''
        One provider digest counts as one delivery even when it contains multiple
        court-slot rows. Verification codes do not count.
        '''
    ),
    block(
        '''
        One provider digest counts as one delivery even when it contains multiple
        court-slot rows. The Web UI displays both tier limits, the current user's sent
        and remaining counts, the Shenzhen-midnight reset, and all exclusions.
        Verification codes do not count.
        '''
    ),
)
