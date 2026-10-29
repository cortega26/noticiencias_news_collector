/** Pure helpers for live collection/publication progress in /triage. */

export interface PublishPhase {
  key: string;
  label: string;
}

/** Six editor-facing publication phases, indexed by backend progress. */
export const PUBLISH_PHASES: readonly PublishPhase[] = [
  { key: 'prep', label: 'Preparando repositorio' },
  { key: 'editor', label: 'Editor IA' },
  { key: 'audit', label: 'Auditoría editorial' },
  { key: 'image', label: 'Imagen' },
  { key: 'validate', label: 'Validación del sitio' },
  { key: 'pr', label: 'Commit y PR' },
];

const COLLECTION_PHASES: Record<string, string> = {
  initialization: 'Inicialización',
  collection: 'Recolección',
  validation: 'Validación',
  scoring: 'Puntuación',
  selection: 'Selección e informe',
  export: 'Exportación',
};

const COLLECTION_STEPS: Record<string, string> = {
  system_initialization: 'Inicializando sistema',
  source_collection: 'Recolectando fuentes',
  validation: 'Validando artículos',
  scoring: 'Calculando puntuaciones',
  final_selection: 'Seleccionando artículos',
  session_report: 'Preparando informe',
  latest_articles_export: 'Exportando resultados',
};

const PUBLICATION_STEPS: Record<string, string> = {
  publication_pipeline_setup: 'Preparando publicación',
  identity_resolution: 'Resolviendo identidad',
  editor_refinement: 'Editando artículo',
  editorial_publication_gates: 'Aplicando controles editoriales',
  image_resolution: 'Resolviendo imagen',
  publication_branch_creation: 'Creando rama',
  publication_post_write: 'Escribiendo artículo',
  frontend_publication_validation: 'Validando el sitio',
  publication_content_fingerprint: 'Verificando el artículo',
  commit_and_push: 'Guardando cambios',
  pull_request_creation: 'Creando pull request',
};

/** Index (0-based) of the phase reported by the backend. */
export function currentPhaseIndex(
  progress: { phase_index?: number | null } | null | undefined
): number {
  const index = progress?.phase_index;
  if (typeof index !== 'number' || !Number.isFinite(index)) return 0;
  return Math.max(0, Math.min(Math.floor(index), PUBLISH_PHASES.length - 1));
}

export function collectPhaseLabel(phaseKey: string | null | undefined): string {
  return phaseKey ? (COLLECTION_PHASES[phaseKey] ?? phaseKey) : 'Preparación';
}

export function collectStepLabel(stepKey: string | null | undefined): string {
  return stepKey ? (COLLECTION_STEPS[stepKey] ?? stepKey) : '';
}

export function publicationStepLabel(stepKey: string | null | undefined): string {
  return stepKey ? (PUBLICATION_STEPS[stepKey] ?? stepKey) : '';
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
  const sec = String(s % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

/** Historical whole-run median presented as an estimate, not a deadline. */
export function describeEta(
  elapsedSeconds: number,
  typicalSeconds: number | null | undefined,
  itemCount = 1
): string {
  if (!typicalSeconds || typicalSeconds <= 0) return 'sin estimado aún';
  const expected = typicalSeconds * Math.max(1, itemCount);
  const remaining = expected - elapsedSeconds;
  if (remaining > 0)
    return `~${formatDuration(remaining)} restantes (habitual ${formatDuration(expected)})`;
  return `superando lo habitual (${formatDuration(expected)})`;
}

function signalAge(seconds: number): string {
  return seconds < 60 ? `${Math.round(seconds)} s` : formatDuration(seconds);
}

/** Separate the backend stage update age from the worker lease heartbeat age. */
export function describeProgressAges(
  nowMs: number,
  progressUpdatedAt: string | null | undefined,
  heartbeatAt: string | null | undefined
): string {
  const progressAge = secondsSinceLastSign(nowMs, progressUpdatedAt);
  const heartbeatAge = secondsSinceLastSign(nowMs, heartbeatAt);
  const parts: string[] = [];
  if (progressAge !== null) parts.push(`fase actualizada hace ${signalAge(progressAge)}`);
  if (heartbeatAge !== null) parts.push(`señal del worker hace ${signalAge(heartbeatAge)}`);
  return parts.join(' · ');
}

/**
 * Seconds since the worker lease heartbeat. The heartbeat ticks every 60 s,
 * so 150 s means at least two missed beats.
 */
export const STALL_AFTER_SECONDS = 150;

export function secondsSinceLastSign(
  nowMs: number,
  ...timestamps: Array<string | null | undefined>
): number | null {
  const latest = Math.max(...timestamps.map((t) => parseServerTime(t) ?? -Infinity));
  return Number.isFinite(latest) ? Math.max(0, (nowMs - latest) / 1000) : null;
}
