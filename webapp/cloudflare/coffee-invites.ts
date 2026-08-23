export const COFFEE_CLAIM_DELAY_MS = 5_000;
export const COFFEE_SESSION_LIFETIME_MS = 10 * 60_000;
export const COFFEE_SESSION_RATE_WINDOW_MS = 60 * 60_000;
export const COFFEE_SESSION_EMAIL_LIMIT = 5;
export const COFFEE_SESSION_IP_LIMIT = 20;
export const COFFEE_INVITE_LIFETIME_MS = 30 * 86_400_000;
export const COFFEE_IP_CLAIM_WINDOW_MS = 30 * 86_400_000;
export const COFFEE_IP_CLAIM_LIMIT = 3;

export type CoffeeSessionState = "claimed" | "too_early" | "expired" | "ready";

export function coffeeSessionState(
  session: {
    claimableAt: number;
    expiresAt: number;
    inviteId?: string | null;
  },
  now: number,
): CoffeeSessionState {
  if (session.inviteId) return "claimed";
  if (now < session.claimableAt) return "too_early";
  if (now >= session.expiresAt) return "expired";
  return "ready";
}

export function coffeeInviteExpiresAt(claimedAt: number): number {
  return claimedAt + COFFEE_INVITE_LIFETIME_MS;
}
