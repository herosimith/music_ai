export type CaptureSignalIssue = "silent" | "too_short";

export interface CaptureSignalSummary {
  durationSeconds: number;
  peak: number;
  peakDbfs: number | null;
  rms: number;
  rmsDbfs: number | null;
  issue: CaptureSignalIssue | null;
}

const MIN_CAPTURE_SECONDS = 0.5;
const MIN_CAPTURE_RMS = 0.003;

export function assessCaptureSignal(
  samples: Float32Array,
  sampleRate: number,
): CaptureSignalSummary {
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) {
    throw new RangeError("sample rate must be positive");
  }
  let peak = 0;
  let squareSum = 0;
  for (const sample of samples) {
    const absolute = Math.abs(sample);
    peak = Math.max(peak, absolute);
    squareSum += sample * sample;
  }
  const rms = samples.length > 0 ? Math.sqrt(squareSum / samples.length) : 0;
  const durationSeconds = samples.length / sampleRate;
  const issue =
    durationSeconds < MIN_CAPTURE_SECONDS
      ? "too_short"
      : rms < MIN_CAPTURE_RMS
        ? "silent"
        : null;
  return {
    durationSeconds,
    peak,
    peakDbfs: amplitudeToDbfs(peak),
    rms,
    rmsDbfs: amplitudeToDbfs(rms),
    issue,
  };
}

export function captureSignalErrorMessage(issue: CaptureSignalIssue): string {
  return issue === "too_short"
    ? "录音时间过短，没有生成可分析的人声。请至少完整唱半秒后再停止。"
    : "录音电平过低，没有检测到可分析的人声。请检查麦克风输入后重唱。";
}

function amplitudeToDbfs(amplitude: number): number | null {
  return amplitude > 0 ? 20 * Math.log10(amplitude) : null;
}
