import { describe, expect, it } from "vitest";

import {
  PRIORITY_EMAIL_GATE_POLL_MS,
  PRIORITY_EMAIL_LEAD_MS,
  PriorityEmailWindowPendingError,
  standardReminderWaitMs,
  waitForSubscriberReminderWindow,
  type PriorityEmailGateSnapshot,
} from "./priority-email-delivery";

const STANDARD_IDLE: PriorityEmailGateSnapshot = {
  recipientTier: "standard",
  priorityOutstanding: false,
  lastPriorityCompletedAt: null,
};

describe("priority subscriber email lead", () => {
  it("never delays the priority recipient", () => {
    expect(standardReminderWaitMs({
      recipientTier: "priority",
      priorityOutstanding: true,
      lastPriorityCompletedAt: 9_999,
    }, 10_000)).toBe(0);
  });

  it("allows a standard reminder when there is no priority activity", () => {
    expect(standardReminderWaitMs(STANDARD_IDLE, 10_000)).toBe(0);
  });

  it("waits the complete remaining lead after the latest priority completion", () => {
    expect(standardReminderWaitMs({
      recipientTier: "standard",
      priorityOutstanding: false,
      lastPriorityCompletedAt: 5_000,
    }, 9_000)).toBe(6_000);
    expect(standardReminderWaitMs({
      recipientTier: "standard",
      priorityOutstanding: false,
      lastPriorityCompletedAt: 5_000,
    }, 5_000 + PRIORITY_EMAIL_LEAD_MS)).toBe(0);
  });

  it("rechecks active priority work and restarts the ten-second window", async () => {
    let current = 1_000;
    const sleeps: number[] = [];
    const snapshots: PriorityEmailGateSnapshot[] = [
      {
        recipientTier: "standard",
        priorityOutstanding: true,
        lastPriorityCompletedAt: null,
      },
      {
        recipientTier: "standard",
        priorityOutstanding: false,
        lastPriorityCompletedAt: 2_000,
      },
      {
        recipientTier: "standard",
        priorityOutstanding: false,
        lastPriorityCompletedAt: 2_000,
      },
    ];

    await waitForSubscriberReminderWindow({}, "standard@example.com", {
      now: () => current,
      sleep: async (delayMs) => {
        sleeps.push(delayMs);
        current += delayMs;
      },
      readSnapshot: async () => snapshots.shift() ?? STANDARD_IDLE,
    });

    expect(sleeps).toEqual([PRIORITY_EMAIL_GATE_POLL_MS, PRIORITY_EMAIL_LEAD_MS]);
    expect(current).toBe(12_000);
  });

  it("defers rather than sending a standard reminder early after the bounded wait", async () => {
    let current = 0;
    const maxWaitMs = 2_500;

    await expect(waitForSubscriberReminderWindow({}, "standard@example.com", {
      now: () => current,
      sleep: async (delayMs) => {
        current += delayMs;
      },
      readSnapshot: async () => ({
        recipientTier: "standard",
        priorityOutstanding: true,
        lastPriorityCompletedAt: null,
      }),
      maxWaitMs,
    })).rejects.toBeInstanceOf(PriorityEmailWindowPendingError);

    expect(current).toBe(maxWaitMs);
  });
});
