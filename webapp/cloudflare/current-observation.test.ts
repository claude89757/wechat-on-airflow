import { describe, expect, it } from "vitest";

import {
  currentObservationSnapshotStatement,
  currentSnapshotMatches,
  type CurrentSnapshotRow,
} from "./current-observation";

const currentSlot = {
  date: "2026-09-02",
  courtName: "1号场",
  startTime: "18:30",
  endTime: "19:30",
};

function row(overrides: Partial<CurrentSnapshotRow> = {}): CurrentSnapshotRow {
  return {
    observation_key: "v3:szw:day-0",
    venue_id: "szw",
    venue_name: "深圳湾",
    healthy: 1,
    checked_at: "2026-09-02T09:55:00.000Z",
    slots_json: JSON.stringify([currentSlot]),
    ...overrides,
  };
}

describe("current observation snapshots", () => {
  it("stores one replaceable snapshot per observation scope", () => {
    const preparedSql: string[] = [];
    const boundArguments: unknown[][] = [];
    const db = {
      prepare(sql: string) {
        preparedSql.push(sql);
        return {
          bind(...values: unknown[]) {
            boundArguments.push(values);
            return {} as D1PreparedStatement;
          },
        } as D1PreparedStatement;
      },
    } as D1Database;

    currentObservationSnapshotStatement(db, {
      observationKey: "v3:szw:day-0",
      venueId: "szw",
      venueName: "深圳湾",
      healthy: true,
      checkedAt: "2026-09-02T09:55:00.000Z",
      error: null,
      slots: [currentSlot],
    }, "2026-09-02T10:00:00.000Z");

    expect(preparedSql[0]).toContain("current_observation_snapshots");
    expect(preparedSql[0]).toContain("ON CONFLICT(observation_key)");
    expect(boundArguments[0]).toEqual([
      "v3:szw:day-0",
      "szw",
      "深圳湾",
      1,
      "2026-09-02T09:55:00.000Z",
      null,
      JSON.stringify([currentSlot]),
      "2026-09-02T10:00:00.000Z",
    ]);
  });

  it("matches future current slots and deduplicates parallel scopes", async () => {
    const matches = await currentSnapshotMatches([
      row(),
      row({ observation_key: "v3:szw:day-1" }),
      row({
        observation_key: "v3:szw:expired",
        slots_json: JSON.stringify([{
          ...currentSlot,
          startTime: "09:00",
          endTime: "10:00",
        }]),
      }),
      row({ observation_key: "v3:szw:unhealthy", healthy: 0 }),
      row({ observation_key: "v3:szw:malformed", slots_json: "not-json" }),
    ], {
      id: "subscription-1",
      email: "user@example.com",
      venueIds: ["szw"],
      weekdayMask: 4,
      startTime: "18:00",
      endTime: "20:00",
    }, new Date("2026-09-02T10:00:00.000Z"));

    expect(matches).toHaveLength(1);
    expect(matches[0].venueId).toBe("szw");
    expect(matches[0].line).toContain("深圳湾1号场");
  });

  it("does not match the wrong weekday, time range, or venue", async () => {
    const rows = [row()];
    const base = {
      id: "subscription-1",
      email: "user@example.com",
      venueIds: ["szw"] as const,
      weekdayMask: 4,
      startTime: "18:00",
      endTime: "20:00",
    };

    expect(await currentSnapshotMatches(rows, {
      ...base,
      venueIds: [...base.venueIds],
      weekdayMask: 8,
    }, new Date("2026-09-02T10:00:00.000Z"))).toHaveLength(0);
    expect(await currentSnapshotMatches(rows, {
      ...base,
      venueIds: [...base.venueIds],
      startTime: "20:00",
      endTime: "21:00",
    }, new Date("2026-09-02T10:00:00.000Z"))).toHaveLength(0);
    expect(await currentSnapshotMatches(rows, {
      ...base,
      venueIds: ["gba"],
    }, new Date("2026-09-02T10:00:00.000Z"))).toHaveLength(0);
  });
});
