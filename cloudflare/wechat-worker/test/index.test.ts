import { afterEach, describe, expect, it, vi } from "vitest";
import worker, { type Env } from "../src/index";

function env(overrides: Partial<Env> = {}): Env {
  return {
    PUBLIC_API_TOKEN: "public-secret",
    SENDER_AGENT_TOKEN: "agent-secret",
    SENDER_AGENT_URL: "http://47.115.144.127:7001",
    ALLOWED_DEVICE_NAME: "971bd67c0107",
    ...overrides,
  };
}

function postRequest(body: unknown, token = "public-secret"): Request {
  return new Request("https://worker.example/v1/wechat/send", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
}

describe("wechat send worker", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("rejects missing public token", async () => {
    const response = await worker.fetch(
      new Request("https://worker.example/v1/wechat/send", {
        method: "POST",
        body: JSON.stringify({
          receiver: "文件传输助手",
          messages: ["hello"],
          device_name: "971bd67c0107",
        }),
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ success: false, error: "unauthorized" });
  });

  it("rejects wrong public token", async () => {
    const response = await worker.fetch(
      postRequest(
        {
          receiver: "文件传输助手",
          messages: ["hello"],
          device_name: "971bd67c0107",
        },
        "wrong-secret",
      ),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ success: false, error: "unauthorized" });
  });

  it("rejects invalid messages", async () => {
    const response = await worker.fetch(
      postRequest({
        receiver: "文件传输助手",
        messages: [],
        device_name: "971bd67c0107",
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ success: false, error: "invalid_request" });
  });

  it("rejects empty message items", async () => {
    const response = await worker.fetch(
      postRequest({
        receiver: "文件传输助手",
        messages: [""],
        device_name: "971bd67c0107",
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ success: false, error: "invalid_request" });
  });

  it("rejects wrong device", async () => {
    const response = await worker.fetch(
      postRequest({
        receiver: "文件传输助手",
        messages: ["hello"],
        device_name: "other-device",
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ success: false, error: "device_not_allowed" });
  });

  it("forwards valid requests to sender-agent", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          success: true,
          device_name: "971bd67c0107",
          receiver: "文件传输助手",
          sent_count: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const response = await worker.fetch(
      postRequest({
        receiver: "文件传输助手",
        messages: ["hello"],
        device_name: "971bd67c0107",
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ success: true, sent_count: 1 });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://47.115.144.127:7001/v1/wechat/send",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer agent-secret",
          "Content-Type": "application/json",
        }),
      }),
    );
  });

  it("passes sender-agent error responses through", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          success: false,
          error: "device_busy",
          message: "device is already sending a message",
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );

    const response = await worker.fetch(
      postRequest({
        receiver: "文件传输助手",
        messages: ["hello"],
        device_name: "971bd67c0107",
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ success: false, error: "device_busy" });
  });

  it("maps sender-agent network failures to upstream_unavailable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("connection refused"));

    const response = await worker.fetch(
      postRequest({
        receiver: "文件传输助手",
        messages: ["hello"],
        device_name: "971bd67c0107",
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({
      success: false,
      error: "upstream_unavailable",
    });
  });
});
