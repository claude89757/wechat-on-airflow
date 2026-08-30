export const DEFAULT_INSPECTION_CADENCE_SECONDS = 60;

const INSPECTION_CADENCE_SECONDS: Readonly<Record<string, number>> = {
  szw: 15,
  dsh: 180,
};

export function inspectionCadenceSeconds(venueId: string): number {
  return INSPECTION_CADENCE_SECONDS[venueId] ?? DEFAULT_INSPECTION_CADENCE_SECONDS;
}

export function formatInspectionCadence(venueId: string): string {
  const seconds = inspectionCadenceSeconds(venueId);
  if (seconds < 60) return `${seconds}秒/次`;
  if (seconds % 60 === 0) return `${seconds / 60}分钟/次`;
  return `${seconds}秒/次`;
}
