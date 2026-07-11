import { describe, expect, it } from "vitest";

import {
  capturePlaybackAnchor,
  captureStartSampleIndex,
  TransportRecorder,
} from "./transport";

describe("TransportRecorder", () => {
  it("records append-only sequence and revision evidence", () => {
    const recorder = new TransportRecorder(48_000);
    const first = recorder.capture(1.25, 6_000);
    const second = recorder.capture(1.5, 18_000);
    const revision = recorder.revise(first.seq, 1.3);

    expect(first).toMatchObject({
      seq: 0,
      revision: 0,
      playheadSamples: 60_000,
      microphoneSampleIndex: 6_000,
      sampleRate: 48_000,
    });
    expect(second.seq).toBe(1);
    expect(revision).toMatchObject({ seq: 0, revision: 1, playheadSamples: 62_400 });
    expect(recorder.snapshot()).toHaveLength(3);
  });

  it("returns defensive snapshots and rejects unknown revisions", () => {
    const recorder = new TransportRecorder(44_100);
    recorder.capture(-1, -10);
    const snapshot = recorder.snapshot();
    snapshot[0].playheadSamples = 99;

    expect(recorder.snapshot()[0].playheadSamples).toBe(0);
    expect(() => recorder.revise(8, 1)).toThrow("transport sequence does not exist");
  });

  it("anchors transport only after playback has actually started", async () => {
    const recorder = new TransportRecorder(48_000);
    let resolvePlayback: (() => void) | undefined;
    let playheadSeconds = 2;
    let microphoneSampleIndex = 0;
    const playback = new Promise<void>((resolve) => {
      resolvePlayback = resolve;
    });

    const anchorPromise = capturePlaybackAnchor(
      recorder,
      () => playback,
      () => playheadSeconds,
      () => microphoneSampleIndex,
    );
    expect(recorder.snapshot()).toEqual([]);

    playheadSeconds = 2.1;
    microphoneSampleIndex = 4_800;
    resolvePlayback?.();
    const anchor = await anchorPromise;

    expect(anchor).toMatchObject({
      playheadSamples: 100_800,
      microphoneSampleIndex: 4_800,
    });
    expect(captureStartSampleIndex(recorder.snapshot())).toBe(4_800);
  });

  it("uses the latest revision of the first sequence for alignment", () => {
    const recorder = new TransportRecorder(48_000);
    recorder.capture(1, 2_400);
    recorder.capture(1.25, 14_400);
    recorder.revise(0, 1.05);

    expect(captureStartSampleIndex(recorder.snapshot())).toBe(2_400);
    expect(captureStartSampleIndex([])).toBe(0);
  });
});
