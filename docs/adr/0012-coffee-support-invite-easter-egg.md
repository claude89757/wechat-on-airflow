# ADR 0012: Coffee Support Invite Easter Egg

- Status: Accepted
- Date: 2026-08-23

## Context

The public Web application needs a small, optional way for users to support the
author with the supplied personal WeChat payment QR. After the QR has been
visible for five seconds, the interface reveals an easter egg that can create a
priority invite valid for redemption for 30 days.

A personal payment QR does not provide this Worker with a payment callback.
Client-side timers are also bypassable, so neither the button label nor a
browser delay can prove that payment occurred.

## Decision

- Keep the QR and coffee action in the responsive Web application and reuse its
  existing bottom-sheet interaction.
- Start the five-second browser timer only after the QR image fires `load`,
  finishes decoding, and crosses a browser paint boundary; keep the claim
  button out of the DOM before the timer completes.
- Require a valid verified-email receipt to start a server session. Store the
  server `shown_at`, a claim boundary exactly five seconds later, and a bounded
  ten-minute expiry; never accept client-supplied timestamps or invite terms.
- Create at most one coffee invite for each verified normalized email. Make
  retries idempotent by returning the same encrypted, recoverable code.
- Create the invitation, unique email claim, and consumed session in one D1
  batch. The code redemption window is exactly 30 days, while a redeemed
  priority tier retains the existing operator-revocation semantics.
- Rate-limit session creation by verified identity and hashed IP, and allow at
  most three successful identities from one hashed IP in a rolling 30 days.
  Enforce both limits inside the conditional database writes so concurrent
  requests cannot pass a check-then-insert race.
- Never log an email, receipt, session identifier, invite code, ciphertext, or
  client IP. Never state that the application verified a WeChat payment.

## Consequences

- The five-second rule is enforced by both the interface and the Worker, and
  concurrent or replayed claims cannot mint additional invitations.
- The verified-email and IP limits make casual automated harvesting materially
  harder without introducing a password account system.
- The feature still cannot establish payment. If the reward becomes valuable
  enough to require payment proof, it must move to a merchant payment callback
  or a deliberate administrator approval flow.
- Migration `0008_add_coffee_invite_claims.sql` must be applied before the new
  Worker is deployed. It only adds tables and is safe for the previous Worker.
