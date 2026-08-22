from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    content = file_path.read_text(encoding="utf-8")
    if content.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}, found {content.count(old)}")
    file_path.write_text(content.replace(old, new), encoding="utf-8")


replace_once(
    "webapp/cloudflare/index.ts",
    '''  const payload = await readJson(request);
  const code = normalizeInviteCode(
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>).code
      : null,
  );
  const now = Date.now();
  const since = now - INVITE_ATTEMPT_WINDOW_MS;
''',
    '''  const now = Date.now();
  const existingPriority = await env.DB.prepare(
    `SELECT tier
       FROM user_delivery_tiers
      WHERE email = ?
        AND tier = 'priority'
        AND revoked_at IS NULL`,
  ).bind(identity.email).first<{ tier: string }>();
  if (existingPriority) {
    const tier: DeliveryTier = "priority";
    const dailyLimit = deliveryLimitForTier(env, tier);
    const dayStart = shanghaiDayStart(new Date(now));
    const sent = await env.DB.prepare(
      `SELECT COUNT(DISTINCT message_id) AS count
         FROM notification_outbox
        WHERE email = ?
          AND status = 'sent'
          AND sent_at >= ?`,
    ).bind(identity.email, dayStart).first<{ count: number }>();
    const remindersToday = Number(sent?.count || 0);
    return json({
      success: true,
      alreadyPriority: true,
      tier,
      dailyLimit,
      remindersToday,
      remainingToday: remainingDailyDeliveries(remindersToday, dailyLimit),
    });
  }

  const payload = await readJson(request);
  const rawCode = payload && typeof payload === "object"
    ? (payload as Record<string, unknown>).code
    : null;
  const since = now - INVITE_ATTEMPT_WINDOW_MS;
''',
)

replace_once(
    "webapp/cloudflare/index.ts",
    '''  if (
    emailAttempts >= INVITE_EMAIL_ATTEMPT_LIMIT
    || ipAttempts >= INVITE_IP_ATTEMPT_LIMIT
  ) {
    return errorResponse(new Error("邀请码验证过于频繁，请稍后再试"), 429);
  }

  const codeHash = await hashInviteCode(code, env.INVITE_CODE_PEPPER);
''',
    '''  if (
    emailAttempts >= INVITE_EMAIL_ATTEMPT_LIMIT
    || ipAttempts >= INVITE_IP_ATTEMPT_LIMIT
  ) {
    return errorResponse(new Error("邀请码验证过于频繁，请稍后再试"), 429);
  }

  let code: string;
  try {
    code = normalizeInviteCode(rawCode);
  } catch (error) {
    await recordInviteAttempt(env, identity.email, ipHash, false, now);
    throw error;
  }
  const codeHash = await hashInviteCode(code, env.INVITE_CODE_PEPPER);
''',
)

replace_once(
    "webapp/src/api.ts",
    '''  success: boolean;
  tier: DeliveryTier;
''',
    '''  success: boolean;
  alreadyPriority?: boolean;
  tier: DeliveryTier;
''',
)

replace_once(
    "webapp/src/Prototype.tsx",
    '''                <strong>3 封/天</strong>
''',
    '''                <strong>默认 3 封/天</strong>
''',
)
replace_once(
    "webapp/src/Prototype.tsx",
    '''                <strong>12 封/天</strong>
''',
    '''                <strong>默认 12 封/天</strong>
''',
)

replace_once(
    "docs/adr/0010-tiered-subscriber-email-and-invites.md",
    '''- Bind priority status to the normalized verified email.
''',
    '''- Bind priority status to the normalized verified email. A successful upgrade
  remains active until an operator explicitly revokes it; invite expiry controls
  only the redemption window.
''',
)

replace_once(
    "docs/runbooks/webapp-deployment.md",
    '''Each code contains 140 bits of cryptographic randomness, expires, and can be
redeemed once. A verified user redeems it from the Web UI. Redemption attempts
are limited per verified email and hashed IP, and old attempt records are
removed automatically.
''',
    '''Each code contains 140 bits of cryptographic randomness, expires, and can be
redeemed once. A verified user redeems it from the Web UI. A successful priority
upgrade remains attached to that normalized email until an operator sets
`revoked_at`; the invite expiry controls only when the code may be redeemed.
Already-priority identities return their current status without consuming
another code. Redemption attempts, including malformed codes, are limited per
verified email and hashed IP, and old attempt records are removed automatically.
''',
)
