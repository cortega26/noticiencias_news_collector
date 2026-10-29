import { describe, expect, it } from 'vitest';

import {
  PUBLISH_PHASES,
  collectPhaseLabel,
  collectStepLabel,
  currentPhaseIndex,
  describeProgressAges,
  describeEta,
  formatDuration,
  parseServerTime,
  publicationStepLabel,
  secondsSinceLastSign,
} from './publishProgress';

describe('server-reported phase and step labels', () => {
  it('uses the backend phase position instead of inferring from completed markers', () => {
    expect(currentPhaseIndex({ phase_index: 1 })).toBe(1);
    expect(currentPhaseIndex({ phase_index: 5 })).toBe(PUBLISH_PHASES.length - 1);
    expect(currentPhaseIndex(null)).toBe(0);
  });

  it('renders the active publication backend step', () => {
    expect(publicationStepLabel('frontend_publication_validation')).toBe('Validando el sitio');
    expect(publicationStepLabel('unknown_backend_step')).toBe('unknown_backend_step');
  });

  it('labels collection phases and steps from backend progress', () => {
    expect(collectPhaseLabel('scoring')).toBe('Puntuación');
    expect(collectStepLabel('session_report')).toBe('Preparando informe');
  });
});

describe('parseServerTime', () => {
  it('treats naive timestamps as UTC', () => {
    expect(parseServerTime('2026-09-29T12:00:00')).toBe(Date.UTC(2026, 8, 29, 12));
    expect(parseServerTime('2026-09-29T12:00:00+00:00')).toBe(Date.UTC(2026, 8, 29, 12));
  });

  it('returns null for empty or invalid input', () => {
    expect(parseServerTime(null)).toBeNull();
    expect(parseServerTime('nope')).toBeNull();
  });
});

describe('formatDuration', () => {
  it('formats m:ss and h:mm:ss', () => {
    expect(formatDuration(5)).toBe('0:05');
    expect(formatDuration(134)).toBe('2:14');
    expect(formatDuration(3725)).toBe('1:02:05');
    expect(formatDuration(-3)).toBe('0:00');
  });
});

describe('describeEta', () => {
  it('reports remaining time against the typical duration', () => {
    expect(describeEta(60, 300)).toBe('~4:00 restantes (habitual 5:00)');
  });

  it('scales the estimate by batch size', () => {
    expect(describeEta(0, 100, 3)).toBe('~5:00 restantes (habitual 5:00)');
  });

  it('flags overruns and missing history', () => {
    expect(describeEta(400, 300)).toBe('superando lo habitual (5:00)');
    expect(describeEta(10, null)).toBe('sin estimado aún');
  });
});

describe('secondsSinceLastSign', () => {
  it('uses the most recent timestamp', () => {
    const now = Date.UTC(2026, 8, 29, 12, 1, 0);
    expect(secondsSinceLastSign(now, '2026-09-29T12:00:00', '2026-09-29T12:00:50Z', null)).toBe(10);
    expect(secondsSinceLastSign(now, null, undefined)).toBeNull();
  });
});

describe('describeProgressAges', () => {
  it('shows the stage-update age separately from the worker heartbeat age', () => {
    const now = Date.UTC(2026, 8, 29, 12, 1, 0);
    expect(describeProgressAges(now, '2026-09-29T12:00:32Z', '2026-09-29T12:00:00Z')).toBe(
      'fase actualizada hace 28 s · señal del worker hace 1:00'
    );
  });
});
