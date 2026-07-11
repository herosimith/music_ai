import { afterEach, describe, expect, it, vi } from "vitest";

import { MicrophoneCapture } from "./capture";

describe("MicrophoneCapture", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("propagates permission denial and remains safe to stop", async () => {
    const getUserMedia = vi
      .fn()
      .mockRejectedValue(new DOMException("Permission denied", "NotAllowedError"));
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    const capture = new MicrophoneCapture();

    await expect(capture.start()).rejects.toMatchObject({ name: "NotAllowedError" });
    await expect(capture.stop()).resolves.toMatchObject({ sampleRate: 48_000 });
    expect(capture.capturedSamples).toBe(0);
  });

  it("releases the media stream when AudioWorklet initialization fails", async () => {
    const stopTrack = vi.fn();
    const closeContext = vi.fn().mockResolvedValue(undefined);
    const getUserMedia = vi.fn().mockResolvedValue({
      getTracks: () => [{ stop: stopTrack }],
    });
    class FailingAudioContext {
      readonly sampleRate = 44_100;
      readonly state = "running";
      readonly audioWorklet = {
        addModule: vi.fn().mockRejectedValue(new Error("worklet unavailable")),
      };
      readonly close = closeContext;
    }
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    vi.stubGlobal("AudioContext", FailingAudioContext);
    const capture = new MicrophoneCapture();

    await expect(capture.start()).rejects.toThrow("worklet unavailable");
    expect(stopTrack).toHaveBeenCalledOnce();
    expect(closeContext).toHaveBeenCalledOnce();
    expect(capture.capturedSamples).toBe(0);
  });

  it("collects PCM chunks from the AudioWorklet and returns them in order", async () => {
    const stopTrack = vi.fn();
    const closeContext = vi.fn().mockResolvedValue(undefined);
    const closePort = vi.fn();
    const port = {
      close: closePort,
      onmessage: null as ((event: MessageEvent<ArrayBuffer>) => void) | null,
    };
    const sink = {
      connect: vi.fn((destination: unknown) => destination),
      disconnect: vi.fn(),
      gain: { value: 1 },
    };
    const worklet = {
      connect: vi.fn((destination: unknown) => destination),
      disconnect: vi.fn(),
      port,
    };
    const source = {
      connect: vi.fn((destination: unknown) => destination),
      disconnect: vi.fn(),
    };
    const getUserMedia = vi.fn().mockResolvedValue({
      getTracks: () => [{ stop: stopTrack }],
    });
    class WorkingAudioContext {
      readonly sampleRate = 48_000;
      readonly state = "running";
      readonly destination = {};
      readonly audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
      readonly createMediaStreamSource = vi.fn(() => source);
      readonly createGain = vi.fn(() => sink);
      readonly resume = vi.fn().mockResolvedValue(undefined);
      readonly close = closeContext;
    }
    class WorkingAudioWorkletNode {
      readonly connect = worklet.connect;
      readonly disconnect = worklet.disconnect;
      readonly port = port;
    }
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    vi.stubGlobal("AudioContext", WorkingAudioContext);
    vi.stubGlobal("AudioWorkletNode", WorkingAudioWorkletNode);
    const capture = new MicrophoneCapture();

    await capture.start();
    port.onmessage?.({ data: new Float32Array([0.1, 0.2]).buffer } as MessageEvent<ArrayBuffer>);
    port.onmessage?.({ data: new Float32Array([0.3]).buffer } as MessageEvent<ArrayBuffer>);
    const result = await capture.stop();

    expect(capture.capturedSamples).toBe(3);
    expect(Array.from(result.samples)).toEqual([
      expect.closeTo(0.1),
      expect.closeTo(0.2),
      expect.closeTo(0.3),
    ]);
    expect(result.sampleRate).toBe(48_000);
    expect(stopTrack).toHaveBeenCalledOnce();
    expect(closeContext).toHaveBeenCalledOnce();
    expect(closePort).toHaveBeenCalledOnce();
  });
});
