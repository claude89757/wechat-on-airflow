import { afterEach, describe, expect, it, vi } from "vitest";

import {
  evaluateWeatherEmailGate,
  resetWeatherEmailGateCacheForTests,
} from "./weather-email-gate";

const NOW = new Date("2026-08-22T01:00:00.000Z");
const ENABLED_ENV = {
  WEATHER_EMAIL_GATE_ENABLED: "true",
  WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM: "2.5",
};

function weatherResponse(precipitationMm: number | null): Response {
  return Response.json({
    daily: {
      time: ["2026-08-22"],
      precipitation_sum: [precipitationMm],
    },
  });
}

describe("Shenzhen weather email gate", () => {
  afterEach(() => {
    resetWeatherEmailGateCacheForTests();
    vi.restoreAllMocks();
  });

  it("does not query weather when the gate is disabled", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    const decision = await evaluateWeatherEmailGate(
      { WEATHER_EMAIL_GATE_ENABLED: "false" },
      { fetchImpl: fetchMock, now: NOW, bypassCache: true },
    );

    expect(decision.sendEmail).toBe(true);
    expect(decision.reason).toBe("gate_disabled");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps subscriber email enabled below the configured threshold", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(weatherResponse(1.2));
    const decision = await evaluateWeatherEmailGate(
      ENABLED_ENV,
      { fetchImpl: fetchMock, now: NOW, bypassCache: true },
    );

    expect(decision).toMatchObject({
      sendEmail: true,
      reason: "precipitation_below_threshold",
      forecastDate: "2026-08-22",
      precipitationMm: 1.2,
      thresholdMm: 2.5,
    });
    const url = fetchMock.mock.calls[0][0] as URL;
    expect(url.searchParams.get("daily")).toBe("precipitation_sum");
    expect(url.searchParams.get("timezone")).toBe("Asia/Shanghai");
    expect(url.searchParams.get("start_date")).toBe("2026-08-22");
    expect(url.searchParams.get("end_date")).toBe("2026-08-22");
  });

  it("suppresses subscriber email when precipitation reaches the threshold", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(weatherResponse(2.5));
    const decision = await evaluateWeatherEmailGate(
      ENABLED_ENV,
      { fetchImpl: fetchMock, now: NOW, bypassCache: true },
    );

    expect(decision).toMatchObject({
      sendEmail: false,
      reason: "precipitation_threshold_met",
      precipitationMm: 2.5,
      thresholdMm: 2.5,
    });
  });

  it("honors a custom precipitation threshold", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(weatherResponse(4.9));
    const decision = await evaluateWeatherEmailGate(
      {
        ...ENABLED_ENV,
        WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM: "5",
      },
      { fetchImpl: fetchMock, now: NOW, bypassCache: true },
    );

    expect(decision.sendEmail).toBe(true);
    expect(decision.thresholdMm).toBe(5);
  });

  it("fails open when the free weather service is unavailable", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(new Error("network down"));
    const decision = await evaluateWeatherEmailGate(
      ENABLED_ENV,
      { fetchImpl: fetchMock, now: NOW, bypassCache: true },
    );

    expect(decision).toMatchObject({
      sendEmail: true,
      reason: "weather_unavailable",
      precipitationMm: null,
      thresholdMm: 2.5,
      error: "network down",
    });
  });

  it("fails open when Open-Meteo returns malformed precipitation data", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ daily: {} }));
    const decision = await evaluateWeatherEmailGate(
      ENABLED_ENV,
      { fetchImpl: fetchMock, now: NOW, bypassCache: true },
    );

    expect(decision.sendEmail).toBe(true);
    expect(decision.reason).toBe("weather_unavailable");
  });

  it("fails open when Open-Meteo returns a null precipitation total", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(weatherResponse(null));
    const decision = await evaluateWeatherEmailGate(
      ENABLED_ENV,
      { fetchImpl: fetchMock, now: NOW, bypassCache: true },
    );

    expect(decision.sendEmail).toBe(true);
    expect(decision.reason).toBe("weather_unavailable");
  });
});
