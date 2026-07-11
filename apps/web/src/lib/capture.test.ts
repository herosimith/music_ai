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
});
