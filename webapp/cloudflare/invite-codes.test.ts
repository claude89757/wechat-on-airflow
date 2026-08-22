import { describe, expect, it } from "vitest";

import {
  formatInviteCode,
  generateInviteCode,
  hashInviteCode,
  normalizeInviteCode,
} from "./invite-codes";

const VALID_CODE = "ACE-SUNNY-PANDA-7K9P2Q";

describe("priority invite codes", () => {
  it("normalizes case, spaces, and separators", () => {
    expect(normalizeInviteCode(" ace sunny panda 7k9p2q ")).toBe(VALID_CODE);
    expect(formatInviteCode("ace_sunny-panda 7k9p2q")).toBe(VALID_CODE);
  });

  it("generates a short memorable phrase with a random suffix", () => {
    const code = generateInviteCode();
    expect(code).toMatch(/^ACE-[A-Z]+-[A-Z]+-[23456789A-HJ-NP-Z]{6}$/);
    expect(code.length).toBeLessThanOrEqual(31);
    expect(normalizeInviteCode(code)).toBe(code);
  });

  it("hashes normalized codes deterministically with a pepper", async () => {
    const first = await hashInviteCode(VALID_CODE, "test-pepper");
    const second = await hashInviteCode(
      "ace sunny panda 7k9p2q",
      "test-pepper",
    );
    expect(first).toBe(second);
    expect(first).toMatch(/^[0-9a-f]{64}$/);
  });

  it("rejects unknown words and ambiguous suffix characters", async () => {
    expect(() => normalizeInviteCode("ACE-UNKNOWN-PANDA-7K9P2Q"))
      .toThrow("邀请码格式无效");
    await expect(hashInviteCode(
      "ACE-SUNNY-PANDA-00O11I",
      "test-pepper",
    )).rejects.toThrow("邀请码格式无效");
  });
});
