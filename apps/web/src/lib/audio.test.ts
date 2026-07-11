import { describe, expect, it } from "vitest";

import {
  createDemoAudio,
  encodeMonoWav,
  formatTime,
  resampleLinear,
  sliceSamples,
} from "./audio";

describe("audio helpers", () => {
  it("encodes a strict mono 16-bit PCM WAV", async () => {
    const blob = encodeMonoWav(new Float32Array([-1, -0.5, 0, 0.5, 1]), 48_000);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const ascii = (start: number, end: number) =>
      String.fromCharCode(...bytes.slice(start, end));

    expect(blob.type).toBe("audio/wav");
    expect(bytes).toHaveLength(54);
    expect(ascii(0, 4)).toBe("RIFF");
    expect(ascii(8, 12)).toBe("WAVE");
    expect(ascii(36, 40)).toBe("data");
    expect(new DataView(bytes.buffer).getUint32(24, true)).toBe(48_000);
    expect(new DataView(bytes.buffer).getUint16(22, true)).toBe(1);
  });

  it("preserves duration when linearly resampling", () => {
    const source = new Float32Array([0, 1, 0, -1]);
    const output = resampleLinear(source, 4, 8);

    expect(output).toHaveLength(8);
    expect(Array.from(output.slice(0, 5))).toEqual([0, 0.5, 1, 0.5, 0]);
    expect(resampleLinear(source, 4, 4)).not.toBe(source);
    expect(() => resampleLinear(source, 0, 4)).toThrow("source sample rate");
  });

  it("creates aligned demo buffers and slices by seconds", () => {
    const demo = createDemoAudio();
    const section = sliceSamples(demo.referenceSamples, demo.sampleRate, 1, 2.5);

    expect(demo.referenceSamples).toHaveLength(demo.durationSeconds * demo.sampleRate);
    expect(demo.userSamples).toHaveLength(demo.referenceSamples.length);
    expect(section).toHaveLength(1.5 * demo.sampleRate);
    expect(formatTime(61.25)).toBe("1:01.3");
    expect(formatTime(Number.NaN)).toBe("0:00.0");
  });
});
