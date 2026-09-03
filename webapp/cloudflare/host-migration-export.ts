type MigrationExportEnv = Env & {
  DB: D1Database;
  AIRFLOW_PUSH_TOKEN: string;
  INVITE_CODE_PEPPER?: string;
  VERIFICATION_PEPPER: string;
};

const ALLOWED_TABLES = new Set([
  "verified_receipts",
  "subscriptions",
  "venue_status",
  "observed_slots",
  "subscription_events",
  "notification_outbox",
  "user_delivery_tiers",
  "priority_invite_codes",
  "priority_invite_attempts",
  "email_delivery_claims",
  "user_profiles",
  "user_roles",
  "system_email_outbox",
  "coffee_invite_sessions",
  "coffee_invite_claims",
]);

function constantTimeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  if (leftBytes.byteLength !== rightBytes.byteLength) return false;
  let difference = 0;
  for (let index = 0; index < leftBytes.byteLength; index += 1) {
    difference |= leftBytes[index] ^ rightBytes[index];
  }
  return difference === 0;
}

function authorized(request: Request, env: MigrationExportEnv): boolean {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) return false;
  const token = authorization.slice(7).trim();
  return Boolean(token) && constantTimeEqual(token, env.AIRFLOW_PUSH_TOKEN);
}

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/")
    + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function inviteEncryptionKey(pepper: string): Promise<CryptoKey> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`zacks-invite-encryption:${pepper}`),
  );
  return crypto.subtle.importKey("raw", digest, { name: "AES-GCM" }, false, ["decrypt"]);
}

async function decryptInviteCode(
  encryptedCode: unknown,
  encryptionIv: unknown,
  pepper: string,
): Promise<string | null> {
  if (typeof encryptedCode !== "string" || typeof encryptionIv !== "string") return null;
  try {
    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: base64UrlToBytes(encryptionIv) },
      await inviteEncryptionKey(pepper),
      base64UrlToBytes(encryptedCode),
    );
    return new TextDecoder().decode(decrypted);
  } catch {
    return null;
  }
}

export async function hostMigrationExport(
  request: Request,
  env: MigrationExportEnv,
): Promise<Response> {
  if (!authorized(request, env)) {
    return Response.json({ error: "未授权" }, { status: 401 });
  }
  const url = new URL(request.url);
  const table = String(url.searchParams.get("table") || "").trim();
  if (!ALLOWED_TABLES.has(table)) {
    return Response.json({ error: "不支持的迁移数据表" }, { status: 400 });
  }
  const cursorValue = Number(url.searchParams.get("cursor") || 0);
  const cursor = Number.isSafeInteger(cursorValue) && cursorValue >= 0 ? cursorValue : 0;
  const requestedLimit = Number(url.searchParams.get("limit") || 250);
  const limit = Number.isSafeInteger(requestedLimit)
    ? Math.min(Math.max(requestedLimit, 1), 500)
    : 250;

  const result = await env.DB.prepare(
    `SELECT rowid AS _cursor, * FROM ${table} WHERE rowid > ? ORDER BY rowid LIMIT ?`,
  ).bind(cursor, limit).all<Record<string, unknown>>();
  const rows = result.results.map((row) => ({ ...row }));
  if (table === "priority_invite_codes") {
    const pepper = env.INVITE_CODE_PEPPER || env.VERIFICATION_PEPPER;
    for (const row of rows) {
      row.plaintext_code = await decryptInviteCode(
        row.encrypted_code,
        row.encryption_iv,
        pepper,
      );
    }
  }
  const nextCursor = rows.length
    ? Number(rows[rows.length - 1]._cursor || cursor)
    : cursor;
  for (const row of rows) delete row._cursor;
  return Response.json({
    schemaVersion: 1,
    table,
    rows,
    nextCursor,
    done: rows.length < limit,
    generatedAt: new Date().toISOString(),
  }, {
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}
