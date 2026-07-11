import { describe, expect, it } from "vitest";

import { assessCaptureSignal, captureSignalErrorMessage } from "./captureSignal";

describe("capture signal gate", () => {
  it("accepts a long enough recording with usable energy", () => {
    const samples = new Float32Array(48_000);
    for (let index = 0; index < samples.length; index += 1) {
      samples[index] = Math.sin((index / 48_000) * Math.PI * 2 * 220) * 0.04;
    }

    const summary = assessCaptureSignal(samples, 48_000);

    expect(summary.issue).toBeNull();
    expect(summary.durationSeconds).toBe(1);
    expect(summary.peak).toBeCloseTo(0.04, 3);
    expect(summary.rmsDbfs).not.toBeNull();
  });

  it("rejects an aligned recording shorter than half a second", () => {
    const summary = assessCaptureSignal(new Float32Array(23_999).fill(0.1), 48_000);

    expect(summary.issue).toBe("too_short");
    expect(captureSignalErrorMessage(summary.issue!)).toContain("至少完整唱半秒");
  });

  it("rejects silence instead of producing a misleading analysis", () => {
    const summary = assessCaptureSignal(new Float32Array(48_000), 48_000);

    expect(summary.issue).toBe("silent");
    expect(summary.rmsDbfs).toBeNull();
    expect(summary.peakDbfs).toBeNull();
    expect(captureSignalErrorMessage(summary.issue!)).toContain("录音电平过低");
  });

  it("accepts sustained low-amplitude audio without requiring a loud peak", () => {
    const samples = new Float32Array(48_000);
    for (let index = 0; index < samples.length; index += 1) {
      samples[index] = Math.sin((index / 48_000) * Math.PI * 2 * 180) * 0.006;
    }

    const summary = assessCaptureSignal(samples, 48_000);

    expect(summary.peak).toBeLessThan(0.015);
    expect(summary.rms).toBeGreaterThan(0.003);
    expect(summary.issue).toBeNull();
  });

  it("rejects invalid sample rates", () => {
    expect(() => assessCaptureSignal(new Float32Array(1), 0)).toThrow(RangeError);
  });
});
