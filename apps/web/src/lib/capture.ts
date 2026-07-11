export interface CapturedAudio {
  samples: Float32Array;
  sampleRate: number;
}

export class MicrophoneCapture {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private sink: GainNode | null = null;
  private readonly chunks: Float32Array[] = [];
  private sampleCount = 0;

  get capturedSamples(): number {
    return this.sampleCount;
  }

  get sampleRate(): number {
    return this.context?.sampleRate ?? 48_000;
  }

  async start(): Promise<void> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      this.context = new AudioContext({ latencyHint: "interactive" });
      await this.context.audioWorklet.addModule("/audio-capture-processor.js");
      this.source = this.context.createMediaStreamSource(this.stream);
      this.worklet = new AudioWorkletNode(this.context, "music-ai-pcm-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      this.sink = this.context.createGain();
      this.sink.gain.value = 0;
      this.worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        const chunk = new Float32Array(event.data);
        this.chunks.push(chunk);
        this.sampleCount += chunk.length;
      };
      this.source.connect(this.worklet).connect(this.sink).connect(this.context.destination);
      await this.context.resume();
    } catch (error) {
      await this.releaseResources();
      throw error;
    }
  }

  async stop(): Promise<CapturedAudio> {
    const sampleRate = this.sampleRate;
    await this.releaseResources();
    const samples = new Float32Array(this.sampleCount);
    let offset = 0;
    for (const chunk of this.chunks) {
      samples.set(chunk, offset);
      offset += chunk.length;
    }
    return { samples, sampleRate };
  }

  private async releaseResources(): Promise<void> {
    this.source?.disconnect();
    this.worklet?.disconnect();
    if (this.worklet) {
      this.worklet.port.onmessage = null;
      this.worklet.port.close();
    }
    this.sink?.disconnect();
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.source = null;
    this.worklet = null;
    this.sink = null;
    this.stream = null;
    this.context = null;
  }
}
