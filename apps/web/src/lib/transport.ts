export interface TransportPoint {
  seq: number;
  revision: number;
  capturedAt: string;
  playheadSamples: number;
  microphoneSampleIndex: number;
  sampleRate: number;
  driftPpm: number;
}

export class TransportRecorder {
  private readonly points: TransportPoint[] = [];
  private sequence = 0;

  constructor(private readonly sampleRate: number) {}

  capture(playheadSeconds: number, microphoneSampleIndex: number): TransportPoint {
    const point: TransportPoint = {
      seq: this.sequence,
      revision: 0,
      capturedAt: new Date().toISOString(),
      playheadSamples: Math.max(0, Math.round(playheadSeconds * this.sampleRate)),
      microphoneSampleIndex: Math.max(0, Math.round(microphoneSampleIndex)),
      sampleRate: this.sampleRate,
      driftPpm: 0,
    };
    this.sequence += 1;
    this.points.push(point);
    return point;
  }

  revise(sequence: number, playheadSeconds: number): TransportPoint {
    const existing = [...this.points].reverse().find((point) => point.seq === sequence);
    if (!existing) throw new Error("transport sequence does not exist");
    const revision: TransportPoint = {
      ...existing,
      revision: existing.revision + 1,
      capturedAt: new Date().toISOString(),
      playheadSamples: Math.max(0, Math.round(playheadSeconds * this.sampleRate)),
    };
    this.points.push(revision);
    return revision;
  }

  snapshot(): TransportPoint[] {
    return this.points.map((point) => ({ ...point }));
  }
}

export async function capturePlaybackAnchor(
  recorder: TransportRecorder,
  startPlayback: () => Promise<void>,
  readPlayheadSeconds: () => number,
  readMicrophoneSampleIndex: () => number,
): Promise<TransportPoint> {
  await startPlayback();
  return recorder.capture(readPlayheadSeconds(), readMicrophoneSampleIndex());
}

export function captureStartSampleIndex(points: readonly TransportPoint[]): number {
  if (points.length === 0) return 0;
  const firstSequence = Math.min(...points.map((point) => point.seq));
  const effectiveFirst = points
    .filter((point) => point.seq === firstSequence)
    .reduce((latest, point) => (point.revision > latest.revision ? point : latest));
  return effectiveFirst.microphoneSampleIndex;
}
