import type { LocalAnalysis } from "../lib/analysis";

export function coachAnalysisFixture(): LocalAnalysis {
  return {
    voicedCoverage: 0.62,
    medianPitchCents: -47,
    onsetOffsetMs: 95,
    stabilityCents: 33,
    confidence: 0.81,
    corrections: [
      {
        id: "local-flat",
        kind: "flat",
        label: "音高偏低",
        detail: "中位偏差 47 音分",
        startSeconds: 0.4,
        endSeconds: 2.6,
        severity: 0.42,
      },
    ],
    coachMessages: ["先用较慢速度循环这一段。"],
  };
}
