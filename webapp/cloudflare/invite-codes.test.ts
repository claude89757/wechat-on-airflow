import { describe, expect, it } from "vitest";

import {
  formatInviteCode,
  generateInviteCode,
  hashInviteCode,
  normalizeInviteCode,
} from "./invite-codes";

const VALID_CODE = "ZACKS-2345678-9ABCDEF-HJKLMNP-QRSTUVW";
const NORMALIZED_VALID_CODE = "ZACKS23456789ABCDEFHJKLMNPQRSTUVW";

describe("priority invite codes", () => {
  it("normalizes case, spaces, and separators", () => {
    expect(normalizeInviteCode(" zacks 2345678 9abcdef h j k l m n p q r s t u v w "))
      .toBe(NORMALIZED_VALID_CODE);
    expect(formatInviteCode(NORMALIZED_VALID_CODE)).toBe(VALID_CODE);
  });

  it("generates a 140-bit human-readable code", () => {
    const code = generateInviteCode();
    expect(code).toMatch(/^ZACKS(?:-[23456789A-HJ-NP-Z]{7}){4}$/);
    expect(normalizeInviteCode(code)).toHaveLength(33);
  });

  it("hashes normalized codes deterministically with a pepper", async () => {
    const first = await hashInviteCode(VALID_CODE, "test-pepper");
    const second = await hashInviteCode(
      NORMALIZED_VALID_CODE.toLowerCase(),
      "test-pepper",
    );
    expect(first).toBe(second);
    expect(first).toMatch(/^[0-9a-f]{64}$/);
  });

  it("rejects malformed and ambiguous codes", async () => {
    expect(() => normalizeInviteCode("ZACKS-short")).toThrow("邀请码格式无效");
    await expect(hashInviteCode(
      "ZACKS-OOOOOOO-OOOOOOO-OOOOOOO-OOOOOOO",
      "test-pepper",
    )).rejects.toThrow("邀请码格式无效");
  });
});
