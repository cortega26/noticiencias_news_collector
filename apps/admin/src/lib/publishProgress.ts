/**
 * Pure helpers for the live publication-progress panel in /triage.
 *
 * The backend reports the completed Refinery stage names of the article in
 * flight (`progress.stages`); this module folds them into the few phases an
 * editor cares about and formats elapsed/estimated time. No DOM here.
 */

export interface PublishPhase {
  key: string;
  label: string;
  /** Stage whose completion closes this phase. */
  marker: string;
}

/** Refinery order (refinery_engine.process_single_article). */
export const PUBLISH_PHASES: readonly PublishPhase[] = [
  { key: "prep", label: "Preparando repositorio", marker: "identity_resolved" },
  { key: "image", label: "Imagen", marker: "image_resolution" },
  { key: "editor", label: "Editor IA", marker: "editor_refinement" },
  { key: "audit", label: "Auditoría editorial", marker: "frontmatter_guard" },
  { key: "validate", label: "Validación del sitio", marker: "frontend_publication_validation" },
  { key: "pr", label: "Commit y PR", marker: "pr_created" },
];

/** Index (0-based) of the phase in progress: one past the furthest marker reached. */
export function currentPhaseIndex(stages: readonly string[] | null | undefined): number {
  let reached = -1;
  for (const stage of stages ?? []) {
    const i = PUBLISH_PHASES.findIndex((p) => p.marker === stage);
    if (i > reached) reached = i;
  }
  return Math.min(reached + 1, PUBLISH_PHASES.length - 1);
}

/** Server timestamps may come back naive (SQLite); those are UTC. */
export function parseServerTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  const ms = Date.parse(hasZone ? value : `${value}Z`);
  return Number.isNaN(ms) ? null : ms;
}

export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** Human estimate text from elapsed vs the median of recent runs. */
export function describeEta(
  elapsedSeconds: number,
  typicalSeconds: number | null | undefined,
  itemCount = 1,
): string {
  if (!typicalSeconds || typicalSeconds <= 0) return "sin estimado aún";
  const expected = typicalSeconds * Math.max(1, itemCount);
  const remaining = expected - elapsedSeconds;
  if (remaining > 0) return `~${formatDuration(remaining)} restantes (habitual ${formatDuration(expected)})`;
  return `superando lo habitual (${formatDuration(expected)})`;
}

/**
 * Seconds without any sign of life before the panel flags a possible hang.
 * The lease heartbeat ticks every 60 s, so 150 s means ≥2 missed beats.
 */
export const STALL_AFTER_SECONDS = 150;

export function secondsSinceLastSign(
  nowMs: number,
  ...timestamps: Array<string | null | undefined>
): number | null {
  const latest = Math.max(...timestamps.map((t) => parseServerTime(t) ?? -Infinity));
  return Number.isFinite(latest) ? Math.max(0, (nowMs - latest) / 1000) : null;
}
