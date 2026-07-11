import { PitchDetector } from "pitchy";

export type CorrectionKind =
  | "flat"
  | "sharp"
  | "early"
  | "late"
  | "unstable"
  | "insufficient";

export interface LocalCorrection {
  id: string;
  kind: CorrectionKind;
  label: string;
  detail: string;
  startSeconds: number;
  endSeconds: number;
  severity: number;
}

export interface LocalAnalysis {
  voicedCoverage: number;
  medianPitchCents: number | null;
  onsetOffsetMs: number | null;
  stabilityCents: number | null;
  confidence: number;
  corrections: LocalCorrection[];
  coachMessages: string[];
}

interface PitchFrame {
  timeSeconds: number;
  pitchHz: number;
  clarity: number;
}

const FRAME_SIZE = 2_048;
const HOP_SIZE = 1_024;

export function analyzeTake(
  reference: Float32Array,
  user: Float32Array,
  sampleRate: number,
): LocalAnalysis {
  const referenceFrames = pitchFrames(reference, sampleRate);
  const userFrames = pitchFrames(user, sampleRate);
  const alignedCount = Math.min(referenceFrames.length, userFrames.length);
  const cents: number[] = [];
  const clarities: number[] = [];
  for (let index = 0; index < alignedCount; index += 1) {
    const expected = referenceFrames[index];
    const observed = userFrames[index];
    if (expected.pitchHz > 0 && observed.pitchHz > 0) {
      cents.push(1_200 * Math.log2(observed.pitchHz / expected.pitchHz));
      clarities.push(Math.min(expected.clarity, observed.clarity));
    }
  }
  const expectedVoiced = referenceFrames.filter((frame) => frame.pitchHz > 0).length;
  const voicedCoverage = expectedVoiced > 0 ? cents.length / expectedVoiced : 0;
  const medianPitchCents = cents.length > 0 ? median(cents) : null;
  const stabilityCents = cents.length > 2 ? standardDeviation(cents) : null;
  const referenceOnset = referenceFrames.find((frame) => frame.pitchHz > 0)?.timeSeconds;
  const userOnset = userFrames.find((frame) => frame.pitchHz > 0)?.timeSeconds;
  const onsetOffsetMs =
    referenceOnset !== undefined && userOnset !== undefined
      ? (userOnset - referenceOnset) * 1_000
      : null;
  const confidence = clarities.length > 0 ? median(clarities) : 0;
  const durationSeconds = reference.length / sampleRate;
  const corrections = buildCorrections({
    voicedCoverage,
    medianPitchCents,
    onsetOffsetMs,
    stabilityCents,
    durationSeconds,
  });
  return {
    voicedCoverage,
    medianPitchCents,
    onsetOffsetMs,
    stabilityCents,
    confidence,
    corrections,
    coachMessages: coachMessages(corrections),
  };
}

function pitchFrames(samples: Float32Array, sampleRate: number): PitchFrame[] {
  const detector = PitchDetector.forFloat32Array(FRAME_SIZE);
  const frames: PitchFrame[] = [];
  for (let offset = 0; offset + FRAME_SIZE <= samples.length; offset += HOP_SIZE) {
    const frame = samples.subarray(offset, offset + FRAME_SIZE);
    const energy = rms(frame);
    if (energy < 0.008) {
      frames.push({ timeSeconds: offset / sampleRate, pitchHz: 0, clarity: 0 });
      continue;
    }
    const [pitchHz, clarity] = detector.findPitch(frame, sampleRate);
    frames.push({
      timeSeconds: offset / sampleRate,
      pitchHz: clarity >= 0.72 && pitchHz >= 55 && pitchHz <= 1_100 ? pitchHz : 0,
      clarity,
    });
  }
  return frames;
}

function buildCorrections({
  voicedCoverage,
  medianPitchCents,
  onsetOffsetMs,
  stabilityCents,
  durationSeconds,
}: {
  voicedCoverage: number;
  medianPitchCents: number | null;
  onsetOffsetMs: number | null;
  stabilityCents: number | null;
  durationSeconds: number;
}): LocalCorrection[] {
  if (voicedCoverage < 0.25 || medianPitchCents === null) {
    return [
      correction(
        "insufficient",
        "有效人声不足",
        "本地预览没有检测到足够稳定的音高帧。",
        durationSeconds,
        1,
      ),
    ];
  }
  const result: LocalCorrection[] = [];
  if (medianPitchCents <= -30) {
    result.push(
      correction(
        "flat",
        "音高偏低",
        `中位偏差 ${Math.abs(Math.round(medianPitchCents))} 音分`,
        durationSeconds,
        Math.min(1, Math.abs(medianPitchCents) / 150),
      ),
    );
  } else if (medianPitchCents >= 30) {
    result.push(
      correction(
        "sharp",
        "音高偏高",
        `中位偏差 ${Math.abs(Math.round(medianPitchCents))} 音分`,
        durationSeconds,
        Math.min(1, Math.abs(medianPitchCents) / 150),
      ),
    );
  }
  if (onsetOffsetMs !== null && Math.abs(onsetOffsetMs) >= 80) {
    const kind = onsetOffsetMs < 0 ? "early" : "late";
    result.push(
      correction(
        kind,
        kind === "early" ? "进入偏早" : "进入偏晚",
        `起音偏差 ${Math.abs(Math.round(onsetOffsetMs))} 毫秒`,
        durationSeconds,
        Math.min(1, Math.abs(onsetOffsetMs) / 300),
      ),
    );
  }
  if (stabilityCents !== null && stabilityCents >= 38) {
    result.push(
      correction(
        "unstable",
        "长音不稳",
        `音高波动 ${Math.round(stabilityCents)} 音分`,
        durationSeconds,
        Math.min(1, stabilityCents / 100),
      ),
    );
  }
  return result;
}

function correction(
  kind: CorrectionKind,
  label: string,
  detail: string,
  durationSeconds: number,
  severity: number,
): LocalCorrection {
  return {
    id: `local-${kind}`,
    kind,
    label,
    detail,
    startSeconds: 0,
    endSeconds: durationSeconds,
    severity,
  };
}

function coachMessages(corrections: LocalCorrection[]): string[] {
  if (corrections.length === 0) {
    return ["没有问题达到本地预览阈值。保持当前方式，再完整唱一遍。"];
  }
  return corrections.slice(0, 2).map((item) => {
    if (item.kind === "flat") return "先用 75% 速度循环这一段，把起始音抬高一些。";
    if (item.kind === "sharp") return "先用 75% 速度循环这一段，放松起始音并向目标音靠拢。";
    if (item.kind === "early" || item.kind === "late") {
      return "跟随伴奏拍点循环三次，只关注进入时机。";
    }
    if (item.kind === "unstable") return "缩短单次气息，先保持音高中心再延长。";
    return "靠近麦克风，用清晰、连续的声音重唱这一段。";
  });
}

function rms(samples: Float32Array): number {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.sqrt(sum / samples.length);
}

function median(values: number[]): number {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 === 0
    ? (ordered[middle - 1] + ordered[middle]) / 2
    : ordered[middle];
}

function standardDeviation(values: number[]): number {
  const center = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance =
    values.reduce((sum, value) => sum + (value - center) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}
