export type DashboardAvailability = "loading" | "ready" | "stale" | "unknown";
export type VenueDisplayState = "healthy" | "unhealthy" | "unknown";

export function resolveDashboardAvailability(input: {
  hasSuccessfulDashboard: boolean;
  loading: boolean;
  refreshFailed: boolean;
}): DashboardAvailability {
  if (!input.hasSuccessfulDashboard) {
    return input.loading ? "loading" : "unknown";
  }
  return input.refreshFailed ? "stale" : "ready";
}

export function resolveVenueDisplayState(
  availability: DashboardAvailability,
  healthy: boolean,
): VenueDisplayState {
  // A cached snapshot is useful history, not proof of current venue health.
  if (availability !== "ready") return "unknown";
  return healthy ? "healthy" : "unhealthy";
}
