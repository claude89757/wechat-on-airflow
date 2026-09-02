import { describe, expect, it } from "vitest";

import {
  FREE_TIER_SCHEMA_MARKER,
  FREE_TIER_SCHEMA_SQL,
  FREE_TIER_SCHEMA_VERSION,
} from "./free-tier-schema";

describe("free-tier schema recovery", () => {
  it("uses one stable marker and idempotent event-driven schema", () => {
    expect(FREE_TIER_SCHEMA_MARKER).toBe("system:free-tier-schema");
    expect(FREE_TIER_SCHEMA_VERSION).toBe("event-driven-observation-v2");
    expect(FREE_TIER_SCHEMA_SQL).toContain(
      "CREATE INDEX IF NOT EXISTS notification_outbox_message_id_lookup_idx",
    );
    expect(FREE_TIER_SCHEMA_SQL).toContain(
      "CREATE INDEX IF NOT EXISTS notification_outbox_submitted_at_lookup_idx",
    );
    expect(FREE_TIER_SCHEMA_SQL).toContain(
      "CREATE INDEX IF NOT EXISTS notification_outbox_delivered_at_lookup_idx",
    );
    expect(FREE_TIER_SCHEMA_SQL).toContain(
      "CREATE TABLE IF NOT EXISTS current_observation_snapshots",
    );
    expect(FREE_TIER_SCHEMA_SQL).toContain(
      "CREATE INDEX IF NOT EXISTS current_observation_snapshots_venue_idx",
    );
    expect(FREE_TIER_SCHEMA_SQL).toContain("PRAGMA optimize;");
    expect(FREE_TIER_SCHEMA_SQL.match(/CREATE INDEX IF NOT EXISTS/g)).toHaveLength(4);
  });
});
