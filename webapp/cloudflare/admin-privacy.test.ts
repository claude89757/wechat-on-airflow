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
