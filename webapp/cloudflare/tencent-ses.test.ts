import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getTencentEmailStatus,
  sendTencentTemplateEmail,
  tencentStatusRequestDates,
} from "./tencent-ses";

const SECRETS = {
  TENCENT_SECRET_ID: "secret-id",
  TENCENT_SECRET_KEY: "secret-key",
  TENCENT_REGION: "ap-guangzhou",
  EMAIL_FROM_ADDRESS: "sender@example.com",
  EMAIL_REPLY_TO: "reply@example.com",
  EMAIL_TEMPLATE_ID: "33340",
};

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
      SECRETS,
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

  it("prefers the send date embedded in the provider MessageId", () => {
    expect(tencentStatusRequestDates(
      "qcloudses-30-4123414323-date-20260824093000-syNARhMTbKI1",
      Date.parse("2026-08-25T12:00:00.000Z"),
    )[0]).toBe("2026-08-24");
  });

  it("queries by MessageId without combining the recipient filter", async () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-08-25T12:00:00.000Z"));
    const messageId = "qcloudses-30-4123414323-date-20260824093000-syNARhMTbKI1";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        Response: {
          EmailStatusList: [{
            MessageId: messageId,
            ToEmailAddress: "recipient@example.com",
            SendStatus: 0,
            DeliverStatus: 1,
          }],
          RequestId: "request-id",
        },
      }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const status = await getTencentEmailStatus(
      SECRETS,
      messageId,
      "recipient@example.com",
    );

    expect(status?.DeliverStatus).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    const payload = JSON.parse(String(request.body)) as Record<string, unknown>;
    expect(payload).toMatchObject({
      RequestDate: "2026-08-24",
      MessageId: messageId,
      Offset: 0,
      Limit: 100,
    });
    expect(payload).not.toHaveProperty("ToEmailAddress");
  });
});
