from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:120]!r}")
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
    'import {\n  deliveryLimitForTier,\n  normalizeDeliveryTier,\n  remainingDailyDeliveries,\n  type DeliveryTier,\n} from "./delivery-tiers";',
    'import {\n  deliveryLimitForTier,\n  deliveryTierLimits,\n  normalizeDeliveryTier,\n  remainingDailyDeliveries,\n  type DeliveryTier,\n} from "./delivery-tiers";',
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
    "    totalVenues: 7,\n  },\n  venues: [",
    "    totalVenues: 7,\n  },\n  deliveryTiers: { standard: 30, priority: 100 },\n  venues: [",
)
replace_once(
    "webapp/src/api.ts",
    "    totalVenues: 7,\n  },\n  venues: FALLBACK_DASHBOARD.venues.map((venue) => ({",
    "    totalVenues: 7,\n  },\n  deliveryTiers: { standard: 30, priority: 100 },\n  venues: FALLBACK_DASHBOARD.venues.map((venue) => ({",
)
replace_all("webapp/src/api.ts", "    dailyLimit: 3,", "    dailyLimit: 30,", 2)
replace_all("webapp/src/api.ts", "    remainingToday: 3,", "    remainingToday: 30,", 2)

replace_once(
    "webapp/src/Prototype.tsx",
    "                      今日已发送 {dashboard.identity.remindersToday}/{dashboard.identity.dailyLimit} 封",
    "                      今日 {dashboard.identity.remindersToday}/{dashboard.identity.dailyLimit} 封\n                      · 还可发送 {dashboard.identity.remainingToday} 封",
)
replace_once(
    "webapp/src/Prototype.tsx",
    '                {dashboard.identity.tier === "priority" ? (\n                  <span className="tier-enabled">优先队列已开启</span>\n                ) : (\n                  <button type="button" onClick={() => openPanel("priority")}>\n                    输入邀请码\n                  </button>\n                )}',
    '                <button\n                  type="button"\n                  className={dashboard.identity.tier === "priority" ? "tier-enabled" : undefined}\n                  onClick={() => openPanel("priority")}\n                >\n                  {dashboard.identity.tier === "priority" ? "查看规则" : "输入邀请码"}\n                </button>',
)
replace_once(
    "webapp/src/Prototype.tsx",
    '            <div className="help-row">\n              <span>3</span>\n              <div><strong>命中后发邮件</strong><p>只有出现符合条件的场地位才会通知，不会重复轰炸。</p></div>\n            </div>',
    '            <div className="help-row">\n              <span>3</span>\n              <div><strong>命中后发邮件</strong><p>同一轮的多个场地和时段会合并为一封摘要邮件。</p></div>\n            </div>\n            <div className="help-row">\n              <span>4</span>\n              <div>\n                <strong>每日邮件额度</strong>\n                <p>\n                  普通用户每天最多 {dashboard.deliveryTiers.standard} 封，优先用户最多\n                  {dashboard.deliveryTiers.priority} 封；按深圳时间 00:00 重置。\n                </p>\n              </div>\n            </div>',
)
replace_once(
    "webapp/src/Prototype.tsx",
    "                <strong>默认 3 封/天</strong>",
    "                <strong>{dashboard.deliveryTiers.standard} 封/天</strong>",
)
replace_once(
    "webapp/src/Prototype.tsx",
    "                <p>适合日常关注；达到上限后，当天后续场地提醒不再补发。</p>",
    "                <p>邮箱验证后自动获得，适合日常关注场地空位。</p>",
)
replace_once(
    "webapp/src/Prototype.tsx",
    "                <strong>默认 12 封/天</strong>",
    "                <strong>{dashboard.deliveryTiers.priority} 封/天</strong>",
)
replace_once(
    "webapp/src/Prototype.tsx",
    "                <p>更高提醒额度，并在系统全局邮件额度紧张时优先处理。</p>",
    "                <p>使用一次性趣味口令升级，全局邮件额度紧张时优先处理。</p>",
)
replace_once(
    "webapp/src/Prototype.tsx",
    '              </article>\n            </div>\n\n            {receipt ? (\n              dashboard.identity.tier === "priority" ? (',
    '              </article>\n            </div>\n\n            <ul className="quota-rules">\n              <li><strong>每天重置：</strong>按深圳时间 00:00 重新计算。</li>\n              <li><strong>摘要计数：</strong>一封邮件可合并多个场地和时段，只计 1 封。</li>\n              <li><strong>达到上限：</strong>当天后续空位邮件不发送，也不会隔天补发旧空位。</li>\n              <li><strong>不计额度：</strong>邮箱验证码和微信消息不受档位限制。</li>\n            </ul>\n\n            {receipt ? (\n              dashboard.identity.tier === "priority" ? (',
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
    "                    邀请码仅可使用一次。验证成功后，优先档位会跟随此邮箱，\n                    更换浏览器重新验证邮箱后仍然有效。",
    "                    这是一个短而有趣的一次性口令，例如\n                    <code className=\"invite-example\">ACE-SUNNY-PANDA-7K9P2Q</code>。\n                    不区分大小写，空格或连字符都可以；升级后优先档位会跟随此邮箱。",
)
replace_once(
    "webapp/src/Prototype.tsx",
    '                    disabled={formBusy || inviteCode.replace(/[^A-Z0-9]/gi, "").length !== 33}',
    '                    disabled={formBusy || inviteCode.trim().length < 12}',
)

css_path = Path("webapp/src/prototype.css")
css = css_path.read_text(encoding="utf-8")
if ".quota-rules {" in css:
    raise RuntimeError("webapp/src/prototype.css: quota rule styles already exist")
css_path.write_text(
    css
    + '''\n\n.quota-rules {\n  display: grid;\n  gap: 9px;\n  margin: 0;\n  padding: 14px 16px;\n  border: 1px solid rgba(42, 112, 105, 0.12);\n  border-radius: 16px;\n  background: #f7fbfa;\n  color: #61736f;\n  font-size: 12px;\n  line-height: 1.55;\n  list-style: none;\n}\n\n.quota-rules li {\n  position: relative;\n  padding-left: 18px;\n}\n\n.quota-rules li::before {\n  position: absolute;\n  top: 0;\n  left: 0;\n  color: var(--teal);\n  content: "✓";\n  font-weight: 800;\n}\n\n.quota-rules strong {\n  color: #244c47;\n}\n\n.invite-example {\n  display: inline-block;\n  margin: 0 4px;\n  padding: 2px 5px;\n  border-radius: 5px;\n  background: #edf6f3;\n  color: #236b63;\n  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;\n  font-size: 10px;\n  font-weight: 700;\n  overflow-wrap: anywhere;\n}\n''',
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
    "weather gate and before Tencent SES delivery. Standard recipients receive up to\nthree digest emails per Shanghai calendar day; priority recipients receive up\nto twelve and are processed first when the global daily provider budget is\nconstrained. Both values are Worker vars.",
    "weather gate and before Tencent SES delivery. Standard recipients receive up to\n30 digest emails per Shanghai calendar day; priority recipients receive up to\n100 and are processed first when the global daily provider budget is\nconstrained. Both values are Worker vars and are returned to the Web client so\nvisible quota copy matches backend enforcement.",
)
replace_once(
    "ARCHITECTURE.md",
    "Priority status is keyed by normalized verified email. A protected internal API\ncreates high-entropy, one-time, expiring invite codes and returns plaintext only\nonce. D1 stores only an HMAC-SHA-256 code hash. Redemption requires a valid\nbrowser receipt and is rate-limited by both verified email and hashed IP.",
    "Priority status is keyed by normalized verified email. A protected internal API\ncreates short, memorable, one-time invite phrases from independently random\nword segments plus an ambiguity-free random suffix, and returns plaintext only\nonce. D1 stores only an HMAC-SHA-256 code hash. Redemption requires a valid\nbrowser receipt and is rate-limited by both verified email and hashed IP.",
)

replace_once(
    "webapp/AGENTS.md",
    "- Subscriber reminder email uses two delivery tiers: standard users receive at\n  most 3 digest deliveries per Shanghai calendar day; priority users receive at\n  most 12 and are ordered first when the global provider budget is constrained.\n  Verification email is never capped. Over-cap venue reminders are suppressed,\n  not deferred, because availability may become stale.\n- Priority status belongs to the verified normalized email. Users redeem a\n  cryptographically random, one-time, expiring invite code; the raw code is\n  returned only at creation time and only its HMAC hash is stored.",
    "- Subscriber reminder email uses two delivery tiers: standard users receive at\n  most 30 digest deliveries per Shanghai calendar day; priority users receive\n  at most 100 and are ordered first when the global provider budget is\n  constrained. Verification email is never capped. Over-cap venue reminders\n  are suppressed, not deferred, because availability may become stale. The Web\n  UI must show both limits, the signed-in identity's sent and remaining counts,\n  the Shanghai-day reset, digest counting, non-replay behavior, and exclusions.\n- Priority status belongs to the verified normalized email. Users redeem a\n  short, memorable, one-time invite phrase such as `ACE-SUNNY-PANDA-7K9P2Q`;\n  the raw phrase is returned only at creation time and only its HMAC hash is\n  stored.",
)

replace_once(
    "docs/adr/0010-tiered-subscriber-email-and-invites.md",
    "- Start with 3 deliveries per day for standard users and 12 for priority users.\n  Both are configuration values and should be reviewed from delivery,\n  suppression, complaint, and engagement data.",
    "- Start with 30 deliveries per day for standard users and 100 for priority users.\n  Both are configuration values, are returned to the Web client for transparent\n  display, and should be reviewed from delivery, suppression, complaint, and\n  engagement data.",
)
replace_once(
    "docs/adr/0010-tiered-subscriber-email-and-invites.md",
    "- Provision one-time expiring invite codes through a separately authenticated\n  internal endpoint. Generate at least 128 bits of CSPRNG entropy, return\n  plaintext once, and store only an HMAC-SHA-256 hash protected by a Worker\n  secret.",
    "- Provision one-time expiring invite phrases through a separately authenticated\n  internal endpoint. Generate two independently random, human-readable word\n  segments plus a six-character ambiguity-free random suffix, return plaintext\n  once, and store only an HMAC-SHA-256 hash protected by a Worker secret. This\n  shorter code is not an authentication session; verified-email and hashed-IP\n  rate limits remain mandatory defenses against online guessing.",
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
    "Each code contains 140 bits of cryptographic randomness, expires, and can be\nredeemed once. A verified user redeems it from the Web UI.",
    "Each code is a short memorable phrase such as\n`ACE-SUNNY-PANDA-7K9P2Q`: two CSPRNG-selected word segments plus a six-character\nambiguity-free random suffix. It expires and can be redeemed once. A verified\nuser redeems it from the Web UI.",
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
    "One provider digest counts as one delivery even when it contains multiple\ncourt-slot rows. Verification codes do not count.",
    "One provider digest counts as one delivery even when it contains multiple\ncourt-slot rows. The Web UI displays both tier limits, the current user's sent\nand remaining counts, the Shenzhen-midnight reset, and all exclusions.\nVerification codes do not count.",
)
