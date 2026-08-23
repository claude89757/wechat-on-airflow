# ADR 0011: Verification email remains on Tencent SES

## Status
Accepted.

## Decision
Email verification, court notifications, and subscription-expiry reminders are sent through
Tencent Cloud SES. Cloudflare remains the application, D1, scheduler, and routing platform.

Cloudflare Email Routing is an inbound-routing product. Email Workers can send through a
`send_email` binding only to destinations allowed by the Email Routing configuration; this is
not a general arbitrary-recipient transactional email quota suitable for addresses entered by
users at runtime. Moving verification messages there would either fail for unregistered
recipients or require pre-registering each user address, so the requested conditional migration
is intentionally not performed.

References:
- https://developers.cloudflare.com/email-routing/
- https://developers.cloudflare.com/email-routing/email-workers/send-email-workers/
- https://cloud.tencent.com/document/product/1288/51053
