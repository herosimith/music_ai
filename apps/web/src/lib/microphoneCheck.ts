export const MICROPHONE_CHECK_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    channelCount: 1,
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false,
  },
};

export type MicrophoneCheckErrorCode =
  | "aborted"
  | "device_unavailable"
  | "not_found"
  | "permission_denied"
  | "permission_timeout"
  | "unsupported";

export class MicrophoneCheckError extends Error {
  constructor(
    readonly code: MicrophoneCheckErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "MicrophoneCheckError";
  }
}

export interface MicrophoneCheckResult {
  deviceLabel: string;
  peakLevel: number;
  signalDetected: boolean;
}

export interface MicrophoneCheckOptions {
  signal?: AbortSignal;
  onLevel?: (level: number) => void;
  sampleFrames?: number;
  sampleIntervalMs?: number;
}

const SIGNAL_THRESHOLD = 0.01;
const MEDIA_PERMISSION_TIMEOUT_MS = 15_000;
const AUDIO_ENGINE_TIMEOUT_MS = 4_000;
const AUDIO_CLOSE_TIMEOUT_MS = 1_000;

export async function checkMicrophone(
  options: MicrophoneCheckOptions = {},
): Promise<MicrophoneCheckResult> {
  const sampleFrames = Math.max(1, Math.min(options.sampleFrames ?? 12, 40));
  const sampleIntervalMs = Math.max(0, Math.min(options.sampleIntervalMs ?? 50, 250));
  let stream: MediaStream | null = null;
  let context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let analyser: AnalyserNode | null = null;
  let sink: GainNode | null = null;

  try {
    throwIfAborted(options.signal);
    if (!navigator.mediaDevices?.getUserMedia || typeof AudioContext === "undefined") {
      throw new MicrophoneCheckError("unsupported", "当前浏览器不支持麦克风检查。");
    }

    const mediaRequest = navigator.mediaDevices.getUserMedia(MICROPHONE_CHECK_CONSTRAINTS);
    try {
      stream = await waitForOperation(
        mediaRequest,
        options.signal,
        MEDIA_PERMISSION_TIMEOUT_MS,
        new MicrophoneCheckError("permission_timeout", "Microphone permission request timed out"),
      );
    } catch (error) {
      void mediaRequest
        .then((lateStream) => {
          for (const track of lateStream.getTracks()) track.stop();
        })
        .catch(() => undefined);
      throw error;
    }
    throwIfAborted(options.signal);
    const track = stream
      .getAudioTracks()
      .find((candidate) => candidate.enabled && candidate.readyState === "live");
    if (!track) {
      throw new MicrophoneCheckError("device_unavailable", "没有可用的实时麦克风音轨。");
    }

    context = new AudioContext({ latencyHint: "interactive" });
    source = context.createMediaStreamSource(stream);
    analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.65;
    sink = context.createGain();
    sink.gain.value = 0;
    source.connect(analyser);
    analyser.connect(sink);
    sink.connect(context.destination);
    await waitForAudioEngine(context.resume(), options.signal);

    const samples = new Float32Array(analyser.fftSize);
    let peakLevel = 0;
    for (let frame = 0; frame < sampleFrames; frame += 1) {
      throwIfAborted(options.signal);
      analyser.getFloatTimeDomainData(samples);
      const level = rootMeanSquare(samples);
      peakLevel = Math.max(peakLevel, level);
      options.onLevel?.(level);
      if (frame + 1 < sampleFrames) {
        await abortableDelay(sampleIntervalMs, options.signal);
      }
    }

    if (!track.enabled || track.readyState !== "live") {
      throw new MicrophoneCheckError("device_unavailable", "麦克风在检查期间断开。");
    }
    return {
      deviceLabel: track.label.trim() || "默认麦克风",
      peakLevel,
      signalDetected: peakLevel >= SIGNAL_THRESHOLD,
    };
  } catch (error) {
    throw normalizeMicrophoneError(error);
  } finally {
    source?.disconnect();
    analyser?.disconnect();
    sink?.disconnect();
    for (const track of stream?.getTracks() ?? []) track.stop();
    if (context && context.state !== "closed") await closeAudioContext(context);
  }
}

export function microphoneCheckErrorMessage(error: unknown): string {
  const normalized = normalizeMicrophoneError(error);
  switch (normalized.code) {
    case "permission_denied":
      return "麦克风权限被拒绝，请在浏览器设置中允许后重试。";
    case "permission_timeout":
      return "麦克风权限请求超时，请处理浏览器权限提示后重试。";
    case "not_found":
      return "没有检测到麦克风设备。";
    case "device_unavailable":
      return "麦克风正被占用、已断开或无法启动。";
    case "unsupported":
      return "当前浏览器不支持麦克风检查。";
    case "aborted":
      return "麦克风检查已取消。";
  }
}

export function isMicrophoneCheckAbort(error: unknown): boolean {
  return normalizeMicrophoneError(error).code === "aborted";
}

function normalizeMicrophoneError(error: unknown): MicrophoneCheckError {
  if (error instanceof MicrophoneCheckError) return error;
  const name = error instanceof DOMException ? error.name : "";
  switch (name) {
    case "AbortError":
      return new MicrophoneCheckError("aborted", "Microphone check was cancelled");
    case "NotAllowedError":
    case "SecurityError":
      return new MicrophoneCheckError("permission_denied", "Microphone permission was denied");
    case "NotFoundError":
    case "DevicesNotFoundError":
      return new MicrophoneCheckError("not_found", "No microphone device was found");
    case "NotReadableError":
    case "TrackStartError":
    case "OverconstrainedError":
      return new MicrophoneCheckError("device_unavailable", "Microphone could not be started");
    default:
      return new MicrophoneCheckError("device_unavailable", "Microphone check failed");
  }
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw new DOMException("Microphone check was cancelled", "AbortError");
  }
}

function abortableDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (milliseconds === 0) {
    throwIfAborted(signal);
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = () => {
      window.clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      reject(new DOMException("Microphone check was cancelled", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function waitForAudioEngine(promise: Promise<void>, signal?: AbortSignal): Promise<void> {
  return waitForOperation(
    promise,
    signal,
    AUDIO_ENGINE_TIMEOUT_MS,
    new MicrophoneCheckError("device_unavailable", "Microphone audio engine timed out"),
  );
}

function waitForOperation<T>(
  promise: Promise<T>,
  signal: AbortSignal | undefined,
  timeoutMs: number,
  timeoutError: MicrophoneCheckError,
): Promise<T> {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      finish(() => reject(timeoutError));
    }, timeoutMs);
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      callback();
    };
    const onAbort = () =>
      finish(() => reject(new DOMException("Microphone check was cancelled", "AbortError")));
    signal?.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => finish(() => resolve(value)),
      (error) => finish(() => reject(error)),
    );
  });
}

async function closeAudioContext(context: AudioContext): Promise<void> {
  let timer = 0;
  await Promise.race([
    context.close().catch(() => undefined),
    new Promise<void>((resolve) => {
      timer = window.setTimeout(resolve, AUDIO_CLOSE_TIMEOUT_MS);
    }),
  ]);
  window.clearTimeout(timer);
}

function rootMeanSquare(samples: Float32Array): number {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.sqrt(sum / samples.length);
}
