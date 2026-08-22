from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def write(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(content).lstrip(), encoding="utf-8")


write(
    "webapp/cloudflare/subscription-terms.ts",
    r'''
    import type { DeliveryTier } from "./delivery-tiers";

    export const STANDARD_SUBSCRIPTION_TERMS = [
      "7d", "8d", "9d", "10d", "11d", "12d", "13d", "14d",
    ] as const;
    export const PRIORITY_EXTRA_SUBSCRIPTION_TERMS = [
      "30d", "90d", "180d", "long_term",
    ] as const;
    export const PRIORITY_SUBSCRIPTION_TERMS = [
      ...STANDARD_SUBSCRIPTION_TERMS,
      ...PRIORITY_EXTRA_SUBSCRIPTION_TERMS,
    ] as const;

    export type StandardSubscriptionTerm = (typeof STANDARD_SUBSCRIPTION_TERMS)[number];
    export type PriorityExtraSubscriptionTerm =
      (typeof PRIORITY_EXTRA_SUBSCRIPTION_TERMS)[number];
    export type SubscriptionTerm = StandardSubscriptionTerm | PriorityExtraSubscriptionTerm;

    export const LONG_TERM_LEASE_DAYS = 90;
    export const LONG_TERM_RENEW_THRESHOLD_DAYS = 45;

    const DAY_MS = 86_400_000;
    const ALL_TERMS = new Set<string>(PRIORITY_SUBSCRIPTION_TERMS);
    const STANDARD_TERMS = new Set<string>(STANDARD_SUBSCRIPTION_TERMS);
    const FIXED_TERM_DAYS: Record<Exclude<SubscriptionTerm, "long_term">, number> = {
      "7d": 7,
      "8d": 8,
      "9d": 9,
      "10d": 10,
      "11d": 11,
      "12d": 12,
      "13d": 13,
      "14d": 14,
      "30d": 30,
      "90d": 90,
      "180d": 180,
    };

    export type ResolvedSubscriptionTerm = {
      termCode: SubscriptionTerm;
      durationDays: number;
      autoRenew: boolean;
      activeUntil: string;
    };

    export function normalizeSubscriptionTerm(
      value: unknown,
      legacyDurationDays?: unknown,
    ): SubscriptionTerm {
      const normalized = String(value ?? "").trim().toLowerCase();
      if (ALL_TERMS.has(normalized)) return normalized as SubscriptionTerm;
      const legacyDays = Number(legacyDurationDays);
      if (Number.isInteger(legacyDays) && legacyDays >= 7 && legacyDays <= 14) {
        return `${legacyDays}d` as StandardSubscriptionTerm;
      }
      throw new Error("订阅有效期无效");
    }

    export function subscriptionTermAllowed(
      tier: DeliveryTier,
      term: SubscriptionTerm,
    ): boolean {
      return tier === "priority" || STANDARD_TERMS.has(term);
    }

    export function subscriptionTermsForTier(tier: DeliveryTier): SubscriptionTerm[] {
      return tier === "priority"
        ? [...PRIORITY_SUBSCRIPTION_TERMS]
        : [...STANDARD_SUBSCRIPTION_TERMS];
    }

    export function resolveSubscriptionTerm(
      term: SubscriptionTerm,
      now = new Date(),
    ): ResolvedSubscriptionTerm {
      const autoRenew = term === "long_term";
      const durationDays = autoRenew ? 0 : FIXED_TERM_DAYS[term];
      const leaseDays = autoRenew ? LONG_TERM_LEASE_DAYS : durationDays;
      return {
        termCode: term,
        durationDays,
        autoRenew,
        activeUntil: new Date(now.getTime() + leaseDays * DAY_MS).toISOString(),
      };
    }
    ''',
)

write(
    "webapp/cloudflare/subscription-terms.test.ts",
    r'''
    import { describe, expect, it } from "vitest";
    import {
      LONG_TERM_LEASE_DAYS,
      normalizeSubscriptionTerm,
      resolveSubscriptionTerm,
      subscriptionTermAllowed,
      subscriptionTermsForTier,
    } from "./subscription-terms";

    describe("subscription term policy", () => {
      it("keeps standard users within seven to fourteen days", () => {
        expect(subscriptionTermsForTier("standard")).toEqual([
          "7d", "8d", "9d", "10d", "11d", "12d", "13d", "14d",
        ]);
        expect(subscriptionTermAllowed("standard", "14d")).toBe(true);
        expect(subscriptionTermAllowed("standard", "30d")).toBe(false);
        expect(subscriptionTermAllowed("standard", "long_term")).toBe(false);
      });

      it("unlocks extended and long-term choices for priority users", () => {
        expect(subscriptionTermAllowed("priority", "30d")).toBe(true);
        expect(subscriptionTermAllowed("priority", "90d")).toBe(true);
        expect(subscriptionTermAllowed("priority", "180d")).toBe(true);
        expect(subscriptionTermAllowed("priority", "long_term")).toBe(true);
      });

      it("accepts the legacy durationDays contract during rollout", () => {
        expect(normalizeSubscriptionTerm(undefined, 7)).toBe("7d");
        expect(normalizeSubscriptionTerm(undefined, 14)).toBe("14d");
        expect(() => normalizeSubscriptionTerm(undefined, 15)).toThrow("订阅有效期无效");
      });

      it("uses a renewable bounded lease for long-term subscriptions", () => {
        const now = new Date("2026-08-23T00:00:00.000Z");
        const resolved = resolveSubscriptionTerm("long_term", now);
        expect(resolved).toEqual({
          termCode: "long_term",
          durationDays: 0,
          autoRenew: true,
          activeUntil: new Date(
            now.getTime() + LONG_TERM_LEASE_DAYS * 86_400_000,
          ).toISOString(),
        });
      });
    });
    ''',
)

write(
    "webapp/cloudflare/admin-privacy.ts",
    r'''
    export type ActivityBucket = "今天活跃" | "7天内活跃" | "30天内活跃" | "较早活跃";
    export type VolumeBucket = "暂无送达" | "1–5封" | "6–20封" | "20封以上";

    export function maskCommunityEmail(email: string): string {
      const [localRaw, domainRaw] = email.toLowerCase().split("@");
      if (!localRaw || !domainRaw) return "***@***";
      const localVisible = localRaw.slice(0, Math.min(2, localRaw.length));
      const localMasked = `${localVisible}${"*".repeat(Math.max(3, localRaw.length - localVisible.length))}`;
      const parts = domainRaw.split(".");
      const host = parts.shift() || "";
      const suffix = parts.length ? `.${parts.join(".")}` : "";
      const hostVisible = host.slice(0, Math.min(1, host.length));
      const hostMasked = `${hostVisible}${"*".repeat(Math.max(3, host.length - hostVisible.length))}`;
      return `${localMasked}@${hostMasked}${suffix}`;
    }

    export function activityBucket(
      timestamp: number | null | undefined,
      now = Date.now(),
    ): ActivityBucket {
      if (!timestamp) return "较早活跃";
      const age = Math.max(0, now - timestamp);
      if (age < 86_400_000) return "今天活跃";
      if (age < 7 * 86_400_000) return "7天内活跃";
      if (age < 30 * 86_400_000) return "30天内活跃";
      return "较早活跃";
    }

    export function volumeBucket(count: number): VolumeBucket {
      if (count <= 0) return "暂无送达";
      if (count <= 5) return "1–5封";
      if (count <= 20) return "6–20封";
      return "20封以上";
    }
    ''',
)

write(
    "webapp/cloudflare/admin-privacy.test.ts",
    r'''
    import { describe, expect, it } from "vitest";
    import { activityBucket, maskCommunityEmail, volumeBucket } from "./admin-privacy";

    describe("community privacy", () => {
      it("masks both mailbox and provider", () => {
        expect(maskCommunityEmail("claudexzt@gmail.com")).toBe("cl*******@g****.com");
      });
      it("coarsens activity and volume", () => {
        const now = Date.UTC(2026, 7, 23);
        expect(activityBucket(now - 3_600_000, now)).toBe("今天活跃");
        expect(activityBucket(now - 5 * 86_400_000, now)).toBe("7天内活跃");
        expect(volumeBucket(0)).toBe("暂无送达");
        expect(volumeBucket(8)).toBe("6–20封");
      });
    });
    ''',
)

write(
    "webapp/cloudflare/email-lifecycle.ts",
    r'''
    export type DeliveryState = "submitted" | "delivered" | "failed";

    export type TencentEmailStatusRecord = {
      MessageId?: string;
      ToEmailAddress?: string;
      SendStatus?: number | string;
      DeliverStatus?: number | string;
      DeliverTime?: number | string;
      DeliverMessage?: string;
    };

    export type NormalizedDeliveryStatus = {
      state: DeliveryState;
      providerStatus: string;
      deliveredAt: string | null;
      error: string | null;
    };

    function validDate(value: unknown): string | null {
      if (value === null || value === undefined || value === "") return null;
      const numeric = Number(value);
      const date = Number.isFinite(numeric) && numeric > 0
        ? new Date(numeric > 10_000_000_000 ? numeric : numeric * 1000)
        : new Date(String(value));
      return Number.isNaN(date.getTime()) ? null : date.toISOString();
    }

    export function normalizeTencentDeliveryStatus(
      record: TencentEmailStatusRecord | null,
    ): NormalizedDeliveryStatus {
      if (!record) {
        return {
          state: "submitted",
          providerStatus: "not_found",
          deliveredAt: null,
          error: null,
        };
      }
      const deliveredAt = validDate(record.DeliverTime);
      const deliver = String(record.DeliverStatus ?? "").trim().toLowerCase();
      const send = String(record.SendStatus ?? "").trim().toLowerCase();
      const message = String(record.DeliverMessage ?? "").trim();
      const explicitDelivered = deliveredAt !== null
        || ["delivered", "success", "succeeded", "投递成功"].includes(deliver);
      if (explicitDelivered) {
        return {
          state: "delivered",
          providerStatus: `send=${send || "unknown"};deliver=${deliver || "delivered"}`,
          deliveredAt: deliveredAt ?? new Date().toISOString(),
          error: null,
        };
      }
      const explicitFailure = [
        "failed", "failure", "bounced", "rejected", "blocked", "2", "3", "4", "5",
      ].includes(deliver)
        || ["failed", "failure", "rejected", "2", "3", "4", "5"].includes(send)
        || Boolean(message && !/success|deliver|投递成功/i.test(message));
      if (explicitFailure) {
        return {
          state: "failed",
          providerStatus: `send=${send || "unknown"};deliver=${deliver || "failed"}`,
          deliveredAt: null,
          error: message || "腾讯云报告邮件投递失败",
        };
      }
      return {
        state: "submitted",
        providerStatus: `send=${send || "unknown"};deliver=${deliver || "pending"}`,
        deliveredAt: null,
        error: null,
      };
    }

    export function shouldEnqueueExpiryReminder(
      activeUntil: string,
      now = new Date(),
    ): boolean {
      const expiry = Date.parse(activeUntil);
      if (!Number.isFinite(expiry)) return false;
      const remaining = expiry - now.getTime();
      return remaining > 0 && remaining <= 86_400_000;
    }
    ''',
)

write(
    "webapp/cloudflare/email-lifecycle.test.ts",
    r'''
    import { describe, expect, it } from "vitest";
    import {
      normalizeTencentDeliveryStatus,
      shouldEnqueueExpiryReminder,
    } from "./email-lifecycle";

    describe("email lifecycle", () => {
      it("does not call an accepted request delivered", () => {
        expect(normalizeTencentDeliveryStatus({ MessageId: "m1" }).state).toBe("submitted");
      });
      it("requires provider delivery evidence", () => {
        const status = normalizeTencentDeliveryStatus({
          MessageId: "m1",
          DeliverTime: "2026-08-23T01:00:00.000Z",
        });
        expect(status.state).toBe("delivered");
        expect(status.deliveredAt).toBe("2026-08-23T01:00:00.000Z");
      });
      it("recognizes provider failures", () => {
        expect(normalizeTencentDeliveryStatus({
          DeliverStatus: "failed",
          DeliverMessage: "mailbox unavailable",
        })).toMatchObject({ state: "failed", error: "mailbox unavailable" });
      });
      it("queues fixed subscriptions only in their final day", () => {
        const now = new Date("2026-08-23T00:00:00.000Z");
        expect(shouldEnqueueExpiryReminder("2026-08-23T20:00:00.000Z", now)).toBe(true);
        expect(shouldEnqueueExpiryReminder("2026-08-25T00:00:00.000Z", now)).toBe(false);
      });
    });
    ''',
)

write(
    "webapp/src/dashboard-state.ts",
    r'''
    export type DashboardAvailability = "loading" | "ready" | "stale" | "unknown";
    export type VenueDisplayState = "healthy" | "unhealthy" | "unknown";

    export function resolveDashboardAvailability(input: {
      hasSuccessfulDashboard: boolean;
      loading: boolean;
      refreshFailed: boolean;
    }): DashboardAvailability {
      if (!input.hasSuccessfulDashboard) {
        return input.loading ? "loading" : "unknown";
      }
      return input.refreshFailed ? "stale" : "ready";
    }

    export function resolveVenueDisplayState(
      availability: DashboardAvailability,
      healthy: boolean,
    ): VenueDisplayState {
      if (availability === "loading" || availability === "unknown") return "unknown";
      return healthy ? "healthy" : "unhealthy";
    }
    ''',
)

write(
    "webapp/cloudflare/dashboard-state.test.ts",
    r'''
    import { describe, expect, it } from "vitest";
    import {
      resolveDashboardAvailability,
      resolveVenueDisplayState,
    } from "../src/dashboard-state";

    describe("dashboard availability", () => {
      it("does not report failures before the first successful bootstrap", () => {
        const availability = resolveDashboardAvailability({
          hasSuccessfulDashboard: false,
          loading: true,
          refreshFailed: false,
        });
        expect(availability).toBe("loading");
        expect(resolveVenueDisplayState(availability, false)).toBe("unknown");
      });
      it("keeps last successful state after refresh failure", () => {
        const availability = resolveDashboardAvailability({
          hasSuccessfulDashboard: true,
          loading: false,
          refreshFailed: true,
        });
        expect(availability).toBe("stale");
        expect(resolveVenueDisplayState(availability, true)).toBe("healthy");
      });
    });
    ''',
)

write(
    "webapp/cloudflare/tencent-ses.ts",
    r'''
    export type TencentSecrets = {
      TENCENT_SECRET_ID: string;
      TENCENT_SECRET_KEY: string;
      TENCENT_REGION: string;
      EMAIL_FROM_ADDRESS: string;
      EMAIL_REPLY_TO: string;
      EMAIL_TEMPLATE_ID: string;
    };

    export type TencentEmailStatus = {
      MessageId?: string;
      ToEmailAddress?: string;
      SendStatus?: number | string;
      DeliverStatus?: number | string;
      DeliverTime?: number | string;
      DeliverMessage?: string;
    };

    const ENDPOINT = "ses.tencentcloudapi.com";
    const SERVICE = "ses";
    const VERSION = "2020-10-02";
    const encoder = new TextEncoder();

    function toHex(value: ArrayBuffer): string {
      return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
    }

    async function sha256(value: string): Promise<ArrayBuffer> {
      return crypto.subtle.digest("SHA-256", encoder.encode(value));
    }

    async function hmac(key: string | ArrayBuffer, value: string): Promise<ArrayBuffer> {
      const imported = await crypto.subtle.importKey(
        "raw",
        typeof key === "string" ? encoder.encode(key) : key,
        { name: "HMAC", hash: "SHA-256" },
        false,
        ["sign"],
      );
      return crypto.subtle.sign("HMAC", imported, encoder.encode(value));
    }

    async function callTencentSes<T>(
      env: TencentSecrets,
      action: string,
      payloadValue: Record<string, unknown>,
    ): Promise<{ response: T; requestId: string | null }> {
      const timestamp = Math.floor(Date.now() / 1000);
      const date = new Date(timestamp * 1000).toISOString().slice(0, 10);
      const payload = JSON.stringify(payloadValue);
      const contentType = "application/json";
      const canonicalHeaders = `content-type:${contentType}\nhost:${ENDPOINT}\n`;
      const signedHeaders = "content-type;host";
      const canonicalRequest = [
        "POST", "/", "", canonicalHeaders, signedHeaders, toHex(await sha256(payload)),
      ].join("\n");
      const credentialScope = `${date}/${SERVICE}/tc3_request`;
      const stringToSign = [
        "TC3-HMAC-SHA256",
        String(timestamp),
        credentialScope,
        toHex(await sha256(canonicalRequest)),
      ].join("\n");
      const secretDate = await hmac(`TC3${env.TENCENT_SECRET_KEY}`, date);
      const secretService = await hmac(secretDate, SERVICE);
      const secretSigning = await hmac(secretService, "tc3_request");
      const signature = toHex(await hmac(secretSigning, stringToSign));
      const authorization = [
        `TC3-HMAC-SHA256 Credential=${env.TENCENT_SECRET_ID}/${credentialScope}`,
        `SignedHeaders=${signedHeaders}`,
        `Signature=${signature}`,
      ].join(", ");
      const httpResponse = await fetch(`https://${ENDPOINT}`, {
        method: "POST",
        headers: {
          Authorization: authorization,
          "Content-Type": contentType,
          "X-TC-Action": action,
          "X-TC-Region": env.TENCENT_REGION,
          "X-TC-Timestamp": String(timestamp),
          "X-TC-Version": VERSION,
        },
        body: payload,
      });
      const result = await httpResponse.json<{
        Response?: T & {
          RequestId?: string;
          Error?: { Code?: string; Message?: string };
        };
      }>();
      const error = result.Response?.Error;
      if (!httpResponse.ok || error || !result.Response) {
        throw new Error(
          `${error?.Code ?? `HTTP_${httpResponse.status}`}: ${error?.Message ?? "腾讯云邮件接口调用失败"}`,
        );
      }
      return {
        response: result.Response,
        requestId: result.Response.RequestId ?? null,
      };
    }

    export async function sendTencentTemplateEmail(
      env: TencentSecrets,
      recipient: string,
      subject: string,
      body: string,
      category = "场地提醒",
    ): Promise<{ messageId: string | null; requestId: string | null }> {
      const result = await callTencentSes<{ MessageId?: string }>(env, "SendEmail", {
        FromEmailAddress: env.EMAIL_FROM_ADDRESS,
        Destination: [recipient],
        Subject: subject,
        Template: {
          TemplateID: Number(env.EMAIL_TEMPLATE_ID),
          TemplateData: JSON.stringify({ COURT_NAME: category, FREE_TIME: body }),
        },
        ReplyToAddresses: env.EMAIL_REPLY_TO,
        TriggerType: 1,
      });
      return {
        messageId: result.response.MessageId ?? null,
        requestId: result.requestId,
      };
    }

    function shanghaiDate(offsetDays = 0): string {
      const shifted = new Date(Date.now() + 8 * 3_600_000 + offsetDays * 86_400_000);
      return shifted.toISOString().slice(0, 10);
    }

    export async function getTencentEmailStatus(
      env: TencentSecrets,
      messageId: string,
      recipient?: string,
    ): Promise<TencentEmailStatus | null> {
      for (const offsetDays of [0, -1, -2]) {
        const result = await callTencentSes<{
          EmailStatusList?: TencentEmailStatus[];
        }>(env, "GetSendEmailStatus", {
          RequestDate: shanghaiDate(offsetDays),
          Offset: 0,
          Limit: 100,
          MessageId: messageId,
          ...(recipient ? { ToEmailAddress: recipient } : {}),
        });
        const match = (result.response.EmailStatusList ?? []).find(
          (item) => item.MessageId === messageId,
        );
        if (match) return match;
      }
      return null;
    }
    ''',
)

write(
    "webapp/migrations/0005_add_subscription_terms.sql",
    r'''
    ALTER TABLE subscriptions ADD COLUMN term_code TEXT NOT NULL DEFAULT 'legacy';
    ALTER TABLE subscriptions ADD COLUMN auto_renew INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE subscriptions ADD COLUMN dedupe_key TEXT;

    UPDATE subscriptions
       SET term_code = CASE
         WHEN duration_days BETWEEN 7 AND 14 THEN CAST(duration_days AS TEXT) || 'd'
         ELSE '14d'
       END
     WHERE term_code = 'legacy';

    CREATE INDEX subscriptions_term_renewal_idx
        ON subscriptions(active, auto_renew, active_until);
    CREATE UNIQUE INDEX subscriptions_active_dedupe_idx
        ON subscriptions(email, dedupe_key)
     WHERE active = 1 AND dedupe_key IS NOT NULL;
    ''',
)

write(
    "webapp/migrations/0006_add_admin_email_lifecycle.sql",
    r'''
    CREATE TABLE user_profiles (
        email TEXT PRIMARY KEY,
        masked_email TEXT NOT NULL,
        first_verified_at INTEGER NOT NULL,
        last_verified_at INTEGER NOT NULL,
        last_login_at INTEGER NOT NULL,
        last_active_at INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );

    INSERT OR IGNORE INTO user_profiles
        (email, masked_email, first_verified_at, last_verified_at,
         last_login_at, last_active_at, created_at, updated_at)
    SELECT email,
           MAX(masked_email),
           MIN(created_at),
           MAX(created_at),
           MAX(last_used_at),
           MAX(last_used_at),
           MIN(created_at),
           MAX(last_used_at)
      FROM verified_receipts
     GROUP BY email;

    CREATE TABLE user_roles (
        email TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin')),
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        revoked_at INTEGER,
        PRIMARY KEY (email, role)
    );
    CREATE INDEX user_roles_active_idx ON user_roles(role, revoked_at);

    INSERT INTO user_roles (email, role, created_at, updated_at, revoked_at)
    VALUES ('claudexzt@gmail.com', 'admin', unixepoch() * 1000, unixepoch() * 1000, NULL)
    ON CONFLICT(email, role) DO UPDATE SET
      updated_at = excluded.updated_at,
      revoked_at = NULL;

    ALTER TABLE priority_invite_codes ADD COLUMN encrypted_code TEXT;
    ALTER TABLE priority_invite_codes ADD COLUMN encryption_iv TEXT;
    ALTER TABLE priority_invite_codes ADD COLUMN code_hint TEXT;
    ALTER TABLE priority_invite_codes ADD COLUMN updated_at INTEGER;
    ALTER TABLE priority_invite_codes ADD COLUMN deleted_at INTEGER;
    UPDATE priority_invite_codes SET updated_at = created_at WHERE updated_at IS NULL;

    ALTER TABLE notification_outbox ADD COLUMN provider_request_id TEXT;
    ALTER TABLE notification_outbox ADD COLUMN provider_status TEXT;
    ALTER TABLE notification_outbox ADD COLUMN provider_submitted_at TEXT;
    ALTER TABLE notification_outbox ADD COLUMN provider_delivered_at TEXT;
    ALTER TABLE notification_outbox ADD COLUMN provider_failed_at TEXT;
    ALTER TABLE notification_outbox ADD COLUMN provider_checked_at INTEGER;
    ALTER TABLE notification_outbox ADD COLUMN provider_error TEXT;

    UPDATE notification_outbox
       SET status = 'submitted',
           provider_status = 'legacy_unverified',
           provider_submitted_at = COALESCE(sent_at, created_at)
     WHERE status = 'sent';
    UPDATE venue_status SET last_notification_at = NULL;

    CREATE INDEX notification_outbox_provider_status_idx
        ON notification_outbox(status, provider_checked_at, provider_submitted_at);

    CREATE TABLE system_email_outbox (
        id TEXT PRIMARY KEY,
        dedupe_key TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL,
        email_type TEXT NOT NULL CHECK (email_type IN ('subscription_expiry')),
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        next_attempt_at INTEGER NOT NULL,
        provider_message_id TEXT,
        provider_request_id TEXT,
        provider_status TEXT,
        submitted_at TEXT,
        delivered_at TEXT,
        failed_at TEXT,
        provider_checked_at INTEGER,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX system_email_outbox_pending_idx
        ON system_email_outbox(status, next_attempt_at);
    CREATE INDEX system_email_outbox_provider_idx
        ON system_email_outbox(status, provider_checked_at, submitted_at);
    ''',
)

write(
    "docs/adr/0011-verification-email-provider.md",
    r'''
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
    ''',
)

write(
    "scripts/accept_webapp_admin.sh",
    r'''
    #!/usr/bin/env bash
    set -euo pipefail

    : "${CLOUDFLARE_ACCOUNT_ID:?}"
    : "${CLOUDFLARE_API_TOKEN:?}"
    target_commit="${1:?target commit required}"
    output_dir="${2:-.local/admin-acceptance}"
    mkdir -p "$output_dir"

    token="acceptance-$(python - <<'PY'
    import secrets
    print(secrets.token_urlsafe(24))
    PY
    )"
    token_hash="$(python - "$token" <<'PY'
    import hashlib,sys
    print(hashlib.sha256(sys.argv[1].encode()).hexdigest())
    PY
    )"
    now_ms="$(python - <<'PY'
    import time
    print(int(time.time()*1000))
    PY
    )"
    expires_ms=$((now_ms + 3600000))

    cleanup() {
      npx wrangler d1 execute zacks-tennis-alerts --remote \
        --command "DELETE FROM verified_receipts WHERE token_hash='$token_hash';" >/dev/null 2>&1 || true
    }
    trap cleanup EXIT

    npx wrangler d1 execute zacks-tennis-alerts --remote --command \
      "INSERT OR REPLACE INTO verified_receipts (token_hash,email,masked_email,expires_at,last_used_at,created_at,revoked_at) VALUES ('$token_hash','claudexzt@gmail.com','cl*******@gmail.com',$expires_ms,$now_ms,$now_ms,NULL);" >/dev/null

    npx wrangler d1 execute zacks-tennis-alerts --remote --json --command \
      "SELECT email,role,revoked_at FROM user_roles WHERE email='claudexzt@gmail.com' AND role='admin';" \
      > "$output_dir/d1-admin.json"

    base="https://zacks.claude89757.cc"
    curl -fsS "$base/api/healthz" > "$output_dir/health.json"
    curl -fsS -H "Authorization: Bearer $token" "$base/api/bootstrap" > "$output_dir/bootstrap.json"
    curl -fsS -H "Authorization: Bearer $token" "$base/api/community/users" > "$output_dir/community.json"
    curl -fsS -H "Authorization: Bearer $token" "$base/api/admin/users" > "$output_dir/admin-users.json"
    curl -fsS -H "Authorization: Bearer $token" "$base/api/admin/invites" > "$output_dir/admin-invites.json"

    community_status="$(curl -sS -o /dev/null -w '%{http_code}' "$base/api/community/users")"
    admin_status="$(curl -sS -o /dev/null -w '%{http_code}' "$base/api/admin/users")"

    python - "$target_commit" "$community_status" "$admin_status" "$output_dir" <<'PY'
    import json, pathlib, sys
    target, community_status, admin_status, output = sys.argv[1:]
    root = pathlib.Path(output)
    health = json.loads((root/'health.json').read_text())
    bootstrap = json.loads((root/'bootstrap.json').read_text())
    community = json.loads((root/'community.json').read_text())
    users = json.loads((root/'admin-users.json').read_text())
    invites = json.loads((root/'admin-invites.json').read_text())
    assert health.get('ok') is True
    deployed = health.get('deploymentCommit') or health.get('deployment_commit')
    if deployed is not None:
        assert deployed == target, (deployed, target)
    assert bootstrap['identity']['verified'] is True
    assert bootstrap['identity']['isAdmin'] is True
    assert isinstance(community.get('users'), list)
    assert isinstance(users.get('users'), list)
    assert isinstance(invites.get('invites'), list)
    assert community_status == '401', community_status
    assert admin_status == '401', admin_status
    for item in community.get('users', []):
        assert '@' in item['email'] and '*' in item['email']
        assert item['email'] != 'claudexzt@gmail.com'
    summary = {
        'ok': True,
        'targetCommit': target,
        'admin': bootstrap['identity']['maskedEmail'],
        'communityUsers': len(community.get('users', [])),
        'adminUsers': len(users.get('users', [])),
        'adminInvites': len(invites.get('invites', [])),
        'anonymousCommunityStatus': community_status,
        'anonymousAdminStatus': admin_status,
    }
    (root/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))
    PY

    asset="$(python - "$output_dir/bootstrap.json" <<'PY'
    import json,sys
    data=json.load(open(sys.argv[1]))
    print(data.get('assetPath',''))
    PY
    )"
    html="$(curl -fsS "$base/")"
    script_path="$(printf '%s' "$html" | grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' | head -1)"
    test -n "$script_path"
    curl -fsS "$base$script_path" > "$output_dir/app.js"
    for phrase in '用户社区' '管理后台' '确认送达' '发送失败'; do
      grep -q "$phrase" "$output_dir/app.js"
    done

    if [ "${RUN_BROWSER_E2E:-true}" = true ]; then
      cat > "$output_dir/e2e.mjs" <<'JS'
      import { chromium } from 'playwright';
      import fs from 'node:fs';
      const [base, token, out] = process.argv.slice(2);
      const browser = await chromium.launch({headless:true});
      const context = await browser.newContext({viewport:{width:390,height:844}});
      const page = await context.newPage();
      const errors=[];
      page.on('console', msg => { if(msg.type()==='error') errors.push(msg.text()); });
      await page.addInitScript(({token}) => {
        localStorage.setItem('zacks-tennis-verified-emails-v1', JSON.stringify([{
          token,
          email:'claudexzt@gmail.com',
          maskedEmail:'cl*******@gmail.com',
          verifiedAt:new Date().toISOString(),
        }]));
      }, {token});
      await page.goto(base, {waitUntil:'networkidle'});
      await page.getByRole('button', {name:/用户社区/}).waitFor();
      await page.getByRole('button', {name:/管理后台/}).waitFor();
      await page.getByRole('button', {name:/用户社区/}).click();
      await page.getByText('社区用户').waitFor();
      await page.keyboard.press('Escape');
      await page.getByRole('button', {name:/管理后台/}).click();
      await page.getByText('邀请码管理').waitFor();
      await page.screenshot({path:`${out}/mobile.png`, fullPage:true});
      fs.writeFileSync(`${out}/browser.json`, JSON.stringify({ok:errors.length===0,errors},null,2));
      if(errors.length) throw new Error(errors.join('\n'));
      await browser.close();
      JS
      node "$output_dir/e2e.mjs" "$base" "$token" "$output_dir"
    fi
    ''',
)

write(
    ".github/workflows/production-admin-acceptance.yml",
    r'''
    name: Production Admin Acceptance
    run-name: production/admin-acceptance/${{ inputs.target_commit }}

    on:
      workflow_dispatch:
        inputs:
          target_commit:
            description: Exact commit SHA on main
            required: true
            type: string
      workflow_call:
        inputs:
          target_commit:
            required: true
            type: string

    permissions:
      contents: read

    concurrency:
      group: production-admin-acceptance
      cancel-in-progress: false

    jobs:
      accept:
        runs-on: ubuntu-latest
        environment: production
        timeout-minutes: 20
        env:
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
        steps:
          - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
            with:
              ref: ${{ inputs.target_commit }}
              fetch-depth: 0
          - name: Validate exact main target
            env:
              TARGET_COMMIT: ${{ inputs.target_commit }}
            run: |
              set -euo pipefail
              test "$(git rev-parse HEAD)" = "$TARGET_COMMIT"
              git fetch --quiet origin main
              git merge-base --is-ancestor "$TARGET_COMMIT" origin/main
          - uses: actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444 # v5
            with:
              node-version: "24"
              cache: npm
              cache-dependency-path: webapp/package-lock.json
          - name: Install Web and browser dependencies
            working-directory: webapp
            run: |
              npm ci
              npx playwright install --with-deps chromium
          - name: Run production acceptance
            env:
              RUN_BROWSER_E2E: "true"
            run: bash scripts/accept_webapp_admin.sh "${{ inputs.target_commit }}" .local/admin-acceptance
          - name: Upload acceptance evidence
            uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
            with:
              name: production-admin-acceptance-${{ github.run_id }}
              path: .local/admin-acceptance
              if-no-files-found: error
              retention-days: 7
    ''',
)
