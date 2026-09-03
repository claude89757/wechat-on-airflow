type MigrationExportEnv = Env & {
  DB: D1Database;
  AIRFLOW_PUSH_TOKEN: string;
  INVITE_CODE_PEPPER?: string;
  VERIFICATION_PEPPER: string;
  TENCENT_SECRET_ID: string;
  TENCENT_SECRET_KEY: string;
  TENCENT_REGION: string;
  EMAIL_FROM_ADDRESS: string;
  EMAIL_REPLY_TO: string;
  EMAIL_TEMPLATE_ID: string;
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

function bytesToBase64Url(value: ArrayBuffer | ArrayBufferView<ArrayBuffer>): string {
  const bytes = value instanceof ArrayBuffer
    ? new Uint8Array(value)
    : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
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

function migrationHeaders(): HeadersInit {
  return {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
  };
}

export async function hostSecretEnvelope(
  request: Request,
  env: MigrationExportEnv,
): Promise<Response> {
  if (!authorized(request, env)) {
    return Response.json({ error: "未授权" }, { status: 401, headers: migrationHeaders() });
  }

  let publicKeySpki: string;
  try {
    const payload = await request.json<{ publicKeySpki?: unknown }>();
    publicKeySpki = typeof payload.publicKeySpki === "string"
      ? payload.publicKeySpki.trim()
      : "";
  } catch {
    publicKeySpki = "";
  }
  if (!publicKeySpki || publicKeySpki.length > 8_192) {
    return Response.json(
      { error: "迁移公钥无效" },
      { status: 400, headers: migrationHeaders() },
    );
  }

  const secretBundle = {
    tencent_secret_id: String(env.TENCENT_SECRET_ID || "").trim(),
    tencent_secret_key: String(env.TENCENT_SECRET_KEY || "").trim(),
    tencent_region: String(env.TENCENT_REGION || "").trim(),
    email_from_address: String(env.EMAIL_FROM_ADDRESS || "").trim(),
    email_reply_to: String(env.EMAIL_REPLY_TO || "").trim(),
    email_template_id: String(env.EMAIL_TEMPLATE_ID || "").trim(),
  };
  const missing = Object.entries(secretBundle)
    .filter(([, value]) => !value)
    .map(([key]) => key);
  if (missing.length) {
    console.error(JSON.stringify({
      event: "host_secret_envelope_unavailable",
      missing,
    }));
    return Response.json(
      { error: "主机邮件配置暂时不可迁移" },
      { status: 503, headers: migrationHeaders() },
    );
  }

  try {
    const publicKey = await crypto.subtle.importKey(
      "spki",
      base64UrlToBytes(publicKeySpki),
      { name: "RSA-OAEP", hash: "SHA-256" },
      false,
      ["encrypt"],
    );
    const aesKeyBytes = crypto.getRandomValues(new Uint8Array(32));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const aesKey = await crypto.subtle.importKey(
      "raw",
      aesKeyBytes,
      { name: "AES-GCM" },
      false,
      ["encrypt"],
    );
    const ciphertext = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      aesKey,
      new TextEncoder().encode(JSON.stringify(secretBundle)),
    );
    const encryptedKey = await crypto.subtle.encrypt(
      { name: "RSA-OAEP" },
      publicKey,
      aesKeyBytes,
    );
    return Response.json({
      algorithm: "RSA-OAEP-256+A256GCM",
      encryptedKey: bytesToBase64Url(encryptedKey),
      iv: bytesToBase64Url(iv),
      ciphertext: bytesToBase64Url(ciphertext),
    }, { headers: migrationHeaders() });
  } catch (error) {
    console.warn(JSON.stringify({
      event: "host_secret_envelope_failed",
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
    return Response.json(
      { error: "迁移公钥无法使用" },
      { status: 400, headers: migrationHeaders() },
    );
  }
}

export async function hostMigrationExport(
  request: Request,
  env: MigrationExportEnv,
): Promise<Response> {
  if (!authorized(request, env)) {
    return Response.json({ error: "未授权" }, { status: 401, headers: migrationHeaders() });
  }
  const url = new URL(request.url);
  const table = String(url.searchParams.get("table") || "").trim();
  if (!ALLOWED_TABLES.has(table)) {
    return Response.json(
      { error: "不支持的迁移数据表" },
      { status: 400, headers: migrationHeaders() },
    );
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
  }, { headers: migrationHeaders() });
}
