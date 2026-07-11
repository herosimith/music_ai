import { describe, expect, it } from "vitest";

import { analyzeTake } from "./analysis";
import { createDemoAudio, synthesizeMelody } from "./audio";

describe("local preview analysis", () => {
  it("detects the demo take's flat and late entrance", () => {
    const demo = createDemoAudio();
    const result = analyzeTake(
      demo.referenceSamples,
      demo.userSamples,
      demo.sampleRate,
    );

    expect(result.voicedCoverage).toBeGreaterThan(0.85);
    expect(result.confidence).toBeGreaterThan(0.8);
    expect(result.medianPitchCents).toBeLessThan(-30);
    expect(result.medianPitchCents).toBeGreaterThan(-60);
    expect(result.onsetOffsetMs).toBeGreaterThanOrEqual(80);
    expect(result.corrections.map((item) => item.kind)).toEqual(
      expect.arrayContaining(["flat", "late"]),
    );
  });

  it("does not invent a correction for an aligned synthetic take", () => {
    const sampleRate = 48_000;
    const reference = synthesizeMelody({ durationSeconds: 4, sampleRate });
    const result = analyzeTake(reference, reference.slice(), sampleRate);

    expect(result.medianPitchCents).toBeCloseTo(0, 3);
    expect(result.onsetOffsetMs).toBe(0);
    expect(result.corrections).toEqual([]);
    expect(result.coachMessages[0]).toContain("没有问题");
  });

  it("fails closed when voiced evidence is insufficient", () => {
    const sampleRate = 48_000;
    const reference = synthesizeMelody({ durationSeconds: 2, sampleRate });
    const result = analyzeTake(reference, new Float32Array(reference.length), sampleRate);

    expect(result.voicedCoverage).toBe(0);
    expect(result.medianPitchCents).toBeNull();
    expect(result.corrections).toHaveLength(1);
    expect(result.corrections[0].kind).toBe("insufficient");
  });
});
