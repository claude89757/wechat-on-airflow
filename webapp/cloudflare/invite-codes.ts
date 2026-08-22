const INVITE_CODE_PREFIX = "ZACKS";
const INVITE_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
const INVITE_CODE_GROUPS = 4;
const INVITE_CODE_GROUP_LENGTH = 7;
const encoder = new TextEncoder();

export type InviteCodeEnv = {
  INVITE_CODE_PEPPER: string;
};

function toHex(value: ArrayBuffer): string {
  return Array.from(
    new Uint8Array(value),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function normalizeInviteCode(value: unknown): string {
  const normalized = String(value || "")
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
  const expectedLength = INVITE_CODE_PREFIX.length
    + INVITE_CODE_GROUPS * INVITE_CODE_GROUP_LENGTH;
  if (
    normalized.length !== expectedLength
    || !normalized.startsWith(INVITE_CODE_PREFIX)
    || !Array.from(normalized.slice(INVITE_CODE_PREFIX.length)).every((character) =>
      INVITE_CODE_ALPHABET.includes(character)
    )
  ) {
    throw new Error("邀请码格式无效");
  }
  return normalized;
}

export function formatInviteCode(normalized: string): string {
  const value = normalizeInviteCode(normalized);
  const payload = value.slice(INVITE_CODE_PREFIX.length);
  const groups = Array.from(
    { length: INVITE_CODE_GROUPS },
    (_, index) => payload.slice(
      index * INVITE_CODE_GROUP_LENGTH,
      (index + 1) * INVITE_CODE_GROUP_LENGTH,
    ),
  );
  return [INVITE_CODE_PREFIX, ...groups].join("-");
}

export function generateInviteCode(): string {
  const bytes = new Uint8Array(INVITE_CODE_GROUPS * INVITE_CODE_GROUP_LENGTH);
  crypto.getRandomValues(bytes);
  const payload = Array.from(
    bytes,
    (byte) => INVITE_CODE_ALPHABET[byte & 31],
  ).join("");
  return formatInviteCode(`${INVITE_CODE_PREFIX}${payload}`);
}

export async function hashInviteCode(
  value: unknown,
  pepper: string,
): Promise<string> {
  if (!pepper) throw new Error("邀请码服务尚未配置");
  const normalized = normalizeInviteCode(value);
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(pepper),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return toHex(await crypto.subtle.sign("HMAC", key, encoder.encode(normalized)));
}
