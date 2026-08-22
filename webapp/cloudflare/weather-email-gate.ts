export type WeatherEmailGateEnv = {
  WEATHER_EMAIL_GATE_ENABLED?: string;
  WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM?: string;
  WEATHER_EMAIL_GATE_LATITUDE?: string;
  WEATHER_EMAIL_GATE_LONGITUDE?: string;
};

export type WeatherEmailGateDecision = {
  sendEmail: boolean;
  reason:
    | "gate_disabled"
    | "precipitation_below_threshold"
    | "precipitation_threshold_met"
    | "weather_unavailable";
  forecastDate: string | null;
  precipitationMm: number | null;
  thresholdMm: number;
  error: string | null;
};

type WeatherEmailGateOptions = {
  now?: Date;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  bypassCache?: boolean;
};

type OpenMeteoResponse = {
  daily?: {
    time?: unknown;
    precipitation_sum?: unknown;
  };
};

type CachedDecision = {
  key: string;
  expiresAt: number;
  decision: WeatherEmailGateDecision;
};

type PendingDecision = {
  key: string;
  promise: Promise<WeatherEmailGateDecision>;
};

const OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast";
const SHENZHEN_LATITUDE = 22.5431;
const SHENZHEN_LONGITUDE = 114.0579;
const DEFAULT_PRECIPITATION_THRESHOLD_MM = 2.5;
const DEFAULT_TIMEOUT_MS = 3_000;
const SUCCESS_CACHE_TTL_MS = 10 * 60_000;
const FAILURE_CACHE_TTL_MS = 60_000;

let cachedDecision: CachedDecision | null = null;
let pendingDecision: PendingDecision | null = null;

function enabled(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes(String(value || "").trim().toLowerCase());
}

function configuredNumber(
  value: string | undefined,
  fallback: number,
  valid: (candidate: number) => boolean,
): number {
  if (value === undefined || value.trim() === "") return fallback;
  const candidate = Number(value);
  return Number.isFinite(candidate) && valid(candidate) ? candidate : fallback;
}

function shanghaiDate(now: Date): string {
  return new Date(now.getTime() + 8 * 3_600_000).toISOString().slice(0, 10);
}

function sanitizeError(error: unknown): string {
  return (error instanceof Error ? error.message : "unknown").slice(0, 160);
}

function failOpen(
  thresholdMm: number,
  forecastDate: string,
  error: unknown,
): WeatherEmailGateDecision {
  return {
    sendEmail: true,
    reason: "weather_unavailable",
    forecastDate,
    precipitationMm: null,
    thresholdMm,
    error: sanitizeError(error),
  };
}

function parsePrecipitation(payload: OpenMeteoResponse, forecastDate: string): number {
  const times = payload.daily?.time;
  const totals = payload.daily?.precipitation_sum;
  if (!Array.isArray(times) || !Array.isArray(totals)) {
    throw new Error("Open-Meteo daily precipitation payload is missing");
  }
  const index = times.indexOf(forecastDate);
  if (index < 0) throw new Error("Open-Meteo response does not include the Shenzhen date");
  const precipitationMm = totals[index];
  if (
    typeof precipitationMm !== "number"
    || !Number.isFinite(precipitationMm)
    || precipitationMm < 0
  ) {
    throw new Error("Open-Meteo precipitation total is invalid");
  }
  return precipitationMm;
}

async function fetchDecision(
  forecastDate: string,
  latitude: number,
  longitude: number,
  thresholdMm: number,
  fetchImpl: typeof fetch,
  timeoutMs: number,
): Promise<WeatherEmailGateDecision> {
  const url = new URL(OPEN_METEO_FORECAST_URL);
  url.searchParams.set("latitude", String(latitude));
  url.searchParams.set("longitude", String(longitude));
  url.searchParams.set("daily", "precipitation_sum");
  url.searchParams.set("timezone", "Asia/Shanghai");
  url.searchParams.set("precipitation_unit", "mm");
  url.searchParams.set("start_date", forecastDate);
  url.searchParams.set("end_date", forecastDate);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(url, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Open-Meteo returned HTTP ${response.status}`);
    const precipitationMm = parsePrecipitation(
      await response.json() as OpenMeteoResponse,
      forecastDate,
    );
    const suppress = precipitationMm >= thresholdMm;
    return {
      sendEmail: !suppress,
      reason: suppress
        ? "precipitation_threshold_met"
        : "precipitation_below_threshold",
      forecastDate,
      precipitationMm,
      thresholdMm,
      error: null,
    };
  } finally {
    clearTimeout(timeout);
  }
}

export async function evaluateWeatherEmailGate(
  env: WeatherEmailGateEnv,
  options: WeatherEmailGateOptions = {},
): Promise<WeatherEmailGateDecision> {
  const thresholdMm = configuredNumber(
    env.WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM,
    DEFAULT_PRECIPITATION_THRESHOLD_MM,
    (candidate) => candidate > 0,
  );
  if (!enabled(env.WEATHER_EMAIL_GATE_ENABLED)) {
    return {
      sendEmail: true,
      reason: "gate_disabled",
      forecastDate: null,
      precipitationMm: null,
      thresholdMm,
      error: null,
    };
  }

  const now = options.now ?? new Date();
  const nowMs = now.getTime();
  const forecastDate = shanghaiDate(now);
  const latitude = configuredNumber(
    env.WEATHER_EMAIL_GATE_LATITUDE,
    SHENZHEN_LATITUDE,
    (candidate) => candidate >= -90 && candidate <= 90,
  );
  const longitude = configuredNumber(
    env.WEATHER_EMAIL_GATE_LONGITUDE,
    SHENZHEN_LONGITUDE,
    (candidate) => candidate >= -180 && candidate <= 180,
  );
  const cacheKey = [forecastDate, latitude, longitude, thresholdMm].join("|");

  if (!options.bypassCache && cachedDecision?.key === cacheKey && cachedDecision.expiresAt > nowMs) {
    return cachedDecision.decision;
  }
  if (!options.bypassCache && pendingDecision?.key === cacheKey) {
    return pendingDecision.promise;
  }

  const fetchImpl = options.fetchImpl ?? fetch;
  const timeoutMs = configuredNumber(
    String(options.timeoutMs ?? DEFAULT_TIMEOUT_MS),
    DEFAULT_TIMEOUT_MS,
    (candidate) => candidate > 0,
  );
  const promise = fetchDecision(
    forecastDate,
    latitude,
    longitude,
    thresholdMm,
    fetchImpl,
    timeoutMs,
  ).catch((error) => failOpen(thresholdMm, forecastDate, error));

  if (!options.bypassCache) pendingDecision = { key: cacheKey, promise };
  try {
    const decision = await promise;
    if (!options.bypassCache) {
      cachedDecision = {
        key: cacheKey,
        expiresAt: nowMs + (
          decision.reason === "weather_unavailable"
            ? FAILURE_CACHE_TTL_MS
            : SUCCESS_CACHE_TTL_MS
        ),
        decision,
      };
    }
    return decision;
  } finally {
    if (!options.bypassCache && pendingDecision?.promise === promise) pendingDecision = null;
  }
}

export function resetWeatherEmailGateCacheForTests(): void {
  cachedDecision = null;
  pendingDecision = null;
}
