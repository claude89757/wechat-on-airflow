const INVITE_CODE_PREFIX = "ACE";
const INVITE_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
const INVITE_CODE_SUFFIX_LENGTH = 6;
const encoder = new TextEncoder();

const INVITE_SCENES = [
  "SUNNY", "BREEZY", "CLOUD", "MOON", "STAR", "COMET", "AURORA", "OCEAN",
  "RIVER", "WAVE", "TIDE", "CORAL", "FOREST", "CEDAR", "MAPLE", "BAMBOO",
  "MEADOW", "GARDEN", "BLOOM", "PEACH", "MANGO", "LEMON", "BERRY", "COCOA",
  "HONEY", "MINT", "LATTE", "MOCHI", "COOKIE", "JELLY", "SUGAR", "SPICE",
  "RALLY", "SERVE", "VOLLEY", "SMASH", "SLICE", "SPIN", "LOB", "COURT",
  "NET", "BASELINE", "MATCH", "SET", "GAME", "BREAK", "FLASH", "TURBO",
  "ROCKET", "NOVA", "PIXEL", "NEON", "MAGIC", "LUCKY", "HAPPY", "BRAVE",
  "QUICK", "CHILL", "GLOW", "DREAM", "PARTY", "FIESTA", "SUNSET", "SUNRISE",
] as const;

const INVITE_MASCOTS = [
  "PANDA", "OTTER", "TIGER", "LION", "FOX", "WOLF", "BEAR", "KOALA",
  "RABBIT", "BUNNY", "DEER", "MOOSE", "HORSE", "ZEBRA", "CAMEL", "LLAMA",
  "ALPACA", "MONKEY", "LEMUR", "SLOTH", "BADGER", "BEAVER", "FERRET", "HEDGEHOG",
  "RACCOON", "SEAL", "DOLPHIN", "WHALE", "SHARK", "TURTLE", "PENGUIN", "PUFFIN",
  "EAGLE", "FALCON", "OWL", "ROBIN", "SPARROW", "PARROT", "TOUCAN", "SWAN",
  "DUCK", "GOOSE", "CRANE", "HERON", "FLAMINGO", "PEACOCK", "GECKO", "IGUANA",
  "COBRA", "DRAGON", "PHOENIX", "UNICORN", "KITTEN", "PUPPY", "HAMSTER", "CHINCHILLA",
  "BISON", "YAK", "ANT", "BEE", "BUTTERFLY", "FIREFLY", "LADYBUG", "MANTIS",
] as const;

export type InviteCodeEnv = {
  INVITE_CODE_PEPPER: string;
};

function toHex(value: ArrayBuffer): string {
  return Array.from(
    new Uint8Array(value),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

function isAllowedSuffix(value: string): boolean {
  return value.length === INVITE_CODE_SUFFIX_LENGTH
    && Array.from(value).every((character) => INVITE_CODE_ALPHABET.includes(character));
}

export function normalizeInviteCode(value: unknown): string {
  const parts = String(value || "")
    .trim()
    .toUpperCase()
    .split(/[^A-Z0-9]+/)
    .filter(Boolean);
  if (
    parts.length !== 4
    || parts[0] !== INVITE_CODE_PREFIX
    || !INVITE_SCENES.includes(parts[1] as (typeof INVITE_SCENES)[number])
    || !INVITE_MASCOTS.includes(parts[2] as (typeof INVITE_MASCOTS)[number])
    || !isAllowedSuffix(parts[3])
  ) {
    throw new Error("邀请码格式无效");
  }
  return parts.join("-");
}

export function formatInviteCode(value: string): string {
  return normalizeInviteCode(value);
}

export function generateInviteCode(): string {
  const bytes = new Uint8Array(2 + INVITE_CODE_SUFFIX_LENGTH);
  crypto.getRandomValues(bytes);
  const scene = INVITE_SCENES[bytes[0] & 63];
  const mascot = INVITE_MASCOTS[bytes[1] & 63];
  const suffix = Array.from(
    bytes.slice(2),
    (byte) => INVITE_CODE_ALPHABET[byte & 31],
  ).join("");
  return `${INVITE_CODE_PREFIX}-${scene}-${mascot}-${suffix}`;
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
