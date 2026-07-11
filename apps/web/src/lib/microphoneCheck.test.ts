import { afterEach, describe, expect, it, vi } from "vitest";

import {
  checkMicrophone,
  isMicrophoneCheckAbort,
  microphoneCheckErrorMessage,
} from "./microphoneCheck";

interface FakeAudioOptions {
  level?: number;
  resumeError?: Error;
  resumePending?: boolean;
}

function installAudioContext(options: FakeAudioOptions = {}) {
  const disconnectSource = vi.fn();
  const disconnectAnalyser = vi.fn();
  const disconnectSink = vi.fn();
  const close = vi.fn().mockResolvedValue(undefined);
  const resume = options.resumePending
    ? vi.fn(() => new Promise<void>(() => undefined))
    : options.resumeError
      ? vi.fn().mockRejectedValue(options.resumeError)
      : vi.fn().mockResolvedValue(undefined);
  const analyser = {
    fftSize: 0,
    smoothingTimeConstant: 0,
    connect: vi.fn(),
    disconnect: disconnectAnalyser,
    getFloatTimeDomainData: vi.fn((samples: Float32Array) => {
      samples.fill(options.level ?? 0);
    }),
  };
  const sink = {
    gain: { value: 1 },
    connect: vi.fn(),
    disconnect: disconnectSink,
  };
  const source = { connect: vi.fn(), disconnect: disconnectSource };

  class FakeAudioContext {
    readonly state = "running";
    readonly destination = {};
    readonly createMediaStreamSource = vi.fn(() => source);
    readonly createAnalyser = vi.fn(() => analyser);
    readonly createGain = vi.fn(() => sink);
    readonly resume = resume;
    readonly close = close;
  }
  vi.stubGlobal("AudioContext", FakeAudioContext);
  return { analyser, close, disconnectAnalyser, disconnectSink, disconnectSource, resume, sink };
}

function installMediaStream(
  track: Partial<MediaStreamTrack> = {},
  getUserMedia = vi.fn(),
) {
  const stop = vi.fn();
  const audioTrack = {
    enabled: true,
    label: "Studio USB Mic",
    readyState: "live",
    stop,
    ...track,
  } as MediaStreamTrack;
  const stream = {
    getAudioTracks: () => [audioTrack],
    getTracks: () => [audioTrack],
  } as MediaStream;
  getUserMedia.mockResolvedValue(stream);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  return { audioTrack, getUserMedia, stop, stream };
}

describe("checkMicrophone", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("passes a live microphone with signal and releases every resource", async () => {
    const media = installMediaStream();
    const audio = installAudioContext({ level: 0.05 });
    const onLevel = vi.fn();

    const result = await checkMicrophone({ onLevel, sampleFrames: 2, sampleIntervalMs: 0 });

    expect(result).toMatchObject({ deviceLabel: "Studio USB Mic", signalDetected: true });
    expect(result.peakLevel).toBeCloseTo(0.05);
    expect(media.getUserMedia).toHaveBeenCalledWith({
      audio: {
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    expect(onLevel).toHaveBeenCalledTimes(2);
    expect(media.stop).toHaveBeenCalledOnce();
    expect(audio.disconnectSource).toHaveBeenCalledOnce();
    expect(audio.disconnectAnalyser).toHaveBeenCalledOnce();
    expect(audio.disconnectSink).toHaveBeenCalledOnce();
    expect(audio.close).toHaveBeenCalledOnce();
  });

  it("passes a live but quiet microphone without claiming signal", async () => {
    installMediaStream({ label: "" });
    installAudioContext({ level: 0 });

    await expect(
      checkMicrophone({ sampleFrames: 1, sampleIntervalMs: 0 }),
    ).resolves.toEqual({ deviceLabel: "默认麦克风", peakLevel: 0, signalDetected: false });
  });

  it("maps permission denial without creating an audio context", async () => {
    const getUserMedia = vi
      .fn()
      .mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    const context = vi.fn();
    vi.stubGlobal("AudioContext", context);

    const promise = checkMicrophone({ sampleFrames: 1 });
    await expect(promise).rejects.toMatchObject({ code: "permission_denied" });
    await promise.catch((error) => {
      expect(microphoneCheckErrorMessage(error)).toContain("权限被拒绝");
    });
    expect(context).not.toHaveBeenCalled();
  });

  it("rejects a missing live audio track and stops the stream", async () => {
    const media = installMediaStream({ enabled: false, readyState: "ended" });
    installAudioContext();

    await expect(checkMicrophone({ sampleFrames: 1 })).rejects.toMatchObject({
      code: "device_unavailable",
    });
    expect(media.stop).toHaveBeenCalledOnce();
  });

  it("releases the stream when AudioContext resume fails", async () => {
    const media = installMediaStream();
    const audio = installAudioContext({ resumeError: new Error("resume failed") });

    await expect(checkMicrophone({ sampleFrames: 1 })).rejects.toMatchObject({
      code: "device_unavailable",
    });
    expect(media.stop).toHaveBeenCalledOnce();
    expect(audio.close).toHaveBeenCalledOnce();
  });

  it("aborts an in-flight check and releases the stream", async () => {
    vi.useFakeTimers();
    const media = installMediaStream();
    installAudioContext({ level: 0.02 });
    const controller = new AbortController();
    const promise = checkMicrophone({
      signal: controller.signal,
      sampleFrames: 3,
      sampleIntervalMs: 100,
    });
    const rejection = expect(promise).rejects.toMatchObject({ code: "aborted" });
    await Promise.resolve();
    controller.abort();
    await vi.runAllTimersAsync();

    await rejection;
    await promise.catch((error) => expect(isMicrophoneCheckAbort(error)).toBe(true));
    expect(media.stop).toHaveBeenCalledOnce();
  });

  it("aborts while the audio engine is still suspended and releases the stream", async () => {
    const media = installMediaStream();
    const audio = installAudioContext({ resumePending: true });
    const controller = new AbortController();
    const promise = checkMicrophone({ signal: controller.signal, sampleFrames: 1 });
    const rejection = expect(promise).rejects.toMatchObject({ code: "aborted" });
    await vi.waitFor(() => expect(audio.resume).toHaveBeenCalledOnce());
    controller.abort();

    await rejection;
    expect(media.stop).toHaveBeenCalledOnce();
    expect(audio.close).toHaveBeenCalledOnce();
  });

  it("fails before requesting media when already aborted", async () => {
    const getUserMedia = vi.fn();
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    vi.stubGlobal("AudioContext", vi.fn());
    const controller = new AbortController();
    controller.abort();

    await expect(checkMicrophone({ signal: controller.signal })).rejects.toMatchObject({
      code: "aborted",
    });
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("aborts a pending permission request and stops a stream that arrives late", async () => {
    const media = installMediaStream();
    let resolveMedia: ((stream: MediaStream) => void) | undefined;
    media.getUserMedia.mockReset().mockReturnValue(
      new Promise<MediaStream>((resolve) => {
        resolveMedia = resolve;
      }),
    );
    vi.stubGlobal("AudioContext", vi.fn());
    const controller = new AbortController();
    const promise = checkMicrophone({ signal: controller.signal });
    const rejection = expect(promise).rejects.toMatchObject({ code: "aborted" });
    controller.abort();

    await rejection;
    resolveMedia?.(media.stream);
    await Promise.resolve();
    await Promise.resolve();
    expect(media.stop).toHaveBeenCalledOnce();
  });

  it("times out a permission request instead of remaining in checking state", async () => {
    vi.useFakeTimers();
    const getUserMedia = vi.fn(() => new Promise<MediaStream>(() => undefined));
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    vi.stubGlobal("AudioContext", vi.fn());
    const promise = checkMicrophone();
    const rejection = expect(promise).rejects.toMatchObject({ code: "permission_timeout" });

    await vi.advanceTimersByTimeAsync(15_000);
    await rejection;
  });

  it("fails closed when media APIs are unavailable", async () => {
    vi.stubGlobal("navigator", {});
    vi.stubGlobal("AudioContext", undefined);

    await expect(checkMicrophone()).rejects.toMatchObject({ code: "unsupported" });
  });
});
