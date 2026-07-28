import { afterEach, describe, expect, it, vi } from "vitest";

import { sendTencentTemplateEmail } from "./tencent-ses";

describe("Tencent SES TC3 request", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("matches the Tencent SDK canonical signed headers", async () => {
    vi.spyOn(Date, "now").mockReturnValue(1_785_249_600_000);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          Response: { MessageId: "message-id", RequestId: "request-id" },
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await sendTencentTemplateEmail(
      {
        TENCENT_SECRET_ID: "secret-id",
        TENCENT_SECRET_KEY: "secret-key",
        TENCENT_REGION: "ap-guangzhou",
        EMAIL_FROM_ADDRESS: "sender@example.com",
        EMAIL_REPLY_TO: "reply@example.com",
        EMAIL_TEMPLATE_ID: "33340",
      },
      "recipient@example.com",
      "subject",
      "body",
    );

    expect(result.messageId).toBe("message-id");
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = request.headers as Record<string, string>;
    const payload = JSON.parse(String(request.body)) as {
      Template: { TemplateData: string };
    };
    expect(JSON.parse(payload.Template.TemplateData)).toEqual({
      COURT_NAME: "场地提醒",
      FREE_TIME: "body",
    });
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers.Authorization).toContain("SignedHeaders=content-type;host");
    expect(headers.Authorization).not.toContain("x-tc-action");
  });
});
