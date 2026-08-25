import { describe, expect, it } from "vitest";
import {
  runEmailReconciliationSafely,
  type EmailReconciliationEnv,
  type EmailReconciliationSummary,
} from "./email-reconciliation";

function testLogger() {
  const info: string[] = [];
  const warnings: string[] = [];
  const errors: string[] = [];
  return {
    info,
    warnings,
    errors,
    logger: {
      info: (message: string) => info.push(message),
      warn: (message: string) => warnings.push(message),
      error: (message: string) => errors.push(message),
    },
  };
}

const EMPTY_SUMMARY: EmailReconciliationSummary = {
  notifications: {
    selected: 0,
    delivered: 0,
    failed: 0,
    pending: 0,
    errors: 0,
  },
  systemEmails: {
    selected: 0,
    delivered: 0,
    failed: 0,
    pending: 0,
    errors: 0,
  },
};

describe("entry email reconciliation", () => {
  it("returns the reconciliation summary when the stage succeeds", async () => {
    const log = testLogger();
    const result = await runEmailReconciliationSafely(
      {} as EmailReconciliationEnv,
      log.logger,
      async () => EMPTY_SUMMARY,
    );

    expect(result).toEqual(EMPTY_SUMMARY);
    expect(log.errors).toEqual([]);
  });

  it("contains a reconciliation failure so later scheduled work can continue", async () => {
    const log = testLogger();
    const result = await runEmailReconciliationSafely(
      {} as EmailReconciliationEnv,
      log.logger,
      async () => {
        throw new Error("provider lookup unavailable");
      },
    );

    expect(result).toBeNull();
    expect(log.errors).toHaveLength(1);
    expect(JSON.parse(log.errors[0])).toMatchObject({
      event: "email_delivery_reconciliation_failed",
      reason: "provider lookup unavailable",
    });
  });
});
