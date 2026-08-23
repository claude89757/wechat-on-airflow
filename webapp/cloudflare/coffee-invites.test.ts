import { describe, expect, it } from "vitest";

import {
  COFFEE_CLAIM_DELAY_MS,
  COFFEE_INVITE_LIFETIME_MS,
  COFFEE_SESSION_LIFETIME_MS,
  coffeeInviteExpiresAt,
  coffeeSessionState,
} from "./coffee-invites";

describe("coffee invite timing", () => {
  const shownAt = 1_787_356_800_000;
  const session = {
    claimableAt: shownAt + COFFEE_CLAIM_DELAY_MS,
    expiresAt: shownAt + COFFEE_SESSION_LIFETIME_MS,
  };

  it("keeps the claim unavailable until five server-timed seconds have elapsed", () => {
    expect(coffeeSessionState(session, session.claimableAt - 1)).toBe("too_early");
    expect(coffeeSessionState(session, session.claimableAt)).toBe("ready");
  });

  it("expires an unclaimed session after ten minutes", () => {
    expect(coffeeSessionState(session, session.expiresAt - 1)).toBe("ready");
    expect(coffeeSessionState(session, session.expiresAt)).toBe("expired");
  });

  it("treats a completed claim as idempotent and gives its code thirty days", () => {
    expect(coffeeSessionState({ ...session, inviteId: "invite-id" }, session.expiresAt + 1))
      .toBe("claimed");
    expect(coffeeInviteExpiresAt(shownAt)).toBe(shownAt + COFFEE_INVITE_LIFETIME_MS);
  });
});
