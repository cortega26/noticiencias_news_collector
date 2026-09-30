import { describe, expect, it } from "vitest";

import {
  PUBLISH_PHASES,
  currentPhaseIndex,
  describeEta,
  formatDuration,
  parseServerTime,
  secondsSinceLastSign,
} from "./publishProgress";

describe("currentPhaseIndex", () => {
  it("starts at the first phase with no stages", () => {
    expect(currentPhaseIndex([])).toBe(0);
    expect(currentPhaseIndex(undefined)).toBe(0);
  });

  it("moves one past the furthest marker reached, ignoring minor stages", () => {
    expect(currentPhaseIndex(["identity_resolved"])).toBe(1);
    expect(currentPhaseIndex(["identity_resolved", "image_resolution"])).toBe(2);
    expect(
      currentPhaseIndex(["identity_resolved", "image_resolution", "editor_refinement", "text_hygiene"]),
    ).toBe(3);
  });

  it("never runs past the last phase", () => {
    expect(currentPhaseIndex(PUBLISH_PHASES.map((p) => p.marker))).toBe(PUBLISH_PHASES.length - 1);
  });
});

describe("parseServerTime", () => {
  it("treats naive timestamps as UTC", () => {
    expect(parseServerTime("2026-09-29T12:00:00")).toBe(Date.UTC(2026, 8, 29, 12));
    expect(parseServerTime("2026-09-29T12:00:00+00:00")).toBe(Date.UTC(2026, 8, 29, 12));
  });

  it("returns null for empty or invalid input", () => {
    expect(parseServerTime(null)).toBeNull();
    expect(parseServerTime("nope")).toBeNull();
  });
});

describe("formatDuration", () => {
  it("formats m:ss and h:mm:ss", () => {
    expect(formatDuration(5)).toBe("0:05");
    expect(formatDuration(134)).toBe("2:14");
    expect(formatDuration(3725)).toBe("1:02:05");
    expect(formatDuration(-3)).toBe("0:00");
  });
});

describe("describeEta", () => {
  it("reports remaining time against the typical duration", () => {
    expect(describeEta(60, 300)).toBe("~4:00 restantes (habitual 5:00)");
  });

  it("scales the estimate by batch size", () => {
    expect(describeEta(0, 100, 3)).toBe("~5:00 restantes (habitual 5:00)");
  });

  it("flags overruns and missing history", () => {
    expect(describeEta(400, 300)).toBe("superando lo habitual (5:00)");
    expect(describeEta(10, null)).toBe("sin estimado aún");
  });
});

describe("secondsSinceLastSign", () => {
  it("uses the most recent timestamp", () => {
    const now = Date.UTC(2026, 8, 29, 12, 1, 0);
    expect(secondsSinceLastSign(now, "2026-09-29T12:00:00", "2026-09-29T12:00:50Z", null)).toBe(10);
    expect(secondsSinceLastSign(now, null, undefined)).toBeNull();
  });
});
