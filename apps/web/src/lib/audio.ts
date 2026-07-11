export const PREVIEW_SAMPLE_RATE = 48_000;

export interface DemoAudio {
  blob: Blob;
  referenceSamples: Float32Array;
  userSamples: Float32Array;
  sampleRate: number;
  durationSeconds: number;
}

export function createDemoAudio(): DemoAudio {
  const durationSeconds = 12;
  const referenceSamples = synthesizeMelody({
    durationSeconds,
    sampleRate: PREVIEW_SAMPLE_RATE,
  });
  const userSamples = synthesizeMelody({
    durationSeconds,
    sampleRate: PREVIEW_SAMPLE_RATE,
    centsOffset: -42,
    delaySeconds: 0.11,
    instabilityCents: 10,
  });
  return {
    blob: encodeMonoWav(referenceSamples, PREVIEW_SAMPLE_RATE),
    referenceSamples,
    userSamples,
    sampleRate: PREVIEW_SAMPLE_RATE,
    durationSeconds,
  };
}

export function synthesizeMelody({
  durationSeconds,
  sampleRate,
  centsOffset = 0,
  delaySeconds = 0,
  instabilityCents = 0,
}: {
  durationSeconds: number;
  sampleRate: number;
  centsOffset?: number;
  delaySeconds?: number;
  instabilityCents?: number;
}): Float32Array {
  const frequencies = [220, 246.942, 261.626, 293.665, 261.626, 246.942];
  const noteSeconds = durationSeconds / frequencies.length;
  const samples = new Float32Array(Math.round(durationSeconds * sampleRate));
  const delaySamples = Math.round(delaySeconds * sampleRate);
  const pitchRatio = 2 ** (centsOffset / 1_200);
  let phase = 0;
  for (let index = delaySamples; index < samples.length; index += 1) {
    const activeTime = (index - delaySamples) / sampleRate;
    const noteIndex = Math.min(
      frequencies.length - 1,
      Math.floor(activeTime / noteSeconds),
    );
    const noteTime = activeTime - noteIndex * noteSeconds;
    const envelope = Math.min(1, noteTime / 0.04, (noteSeconds - noteTime) / 0.08);
    const vibrato = instabilityCents * Math.sin(2 * Math.PI * 5.2 * activeTime);
    const frequency = frequencies[noteIndex] * pitchRatio * 2 ** (vibrato / 1_200);
    phase += (2 * Math.PI * frequency) / sampleRate;
    samples[index] = Math.sin(phase) * Math.max(0, envelope) * 0.46;
  }
  return samples;
}

export function encodeMonoWav(samples: Float32Array, sampleRate: number): Blob {
  const payloadLength = samples.length * 2;
  const buffer = new ArrayBuffer(44 + payloadLength);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + payloadLength, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, payloadLength, true);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, sample < 0 ? sample * 32_768 : sample * 32_767, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export async function decodeAudioBlob(blob: Blob): Promise<{
  samples: Float32Array;
  sampleRate: number;
}> {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    const mono = new Float32Array(decoded.length);
    for (let channel = 0; channel < decoded.numberOfChannels; channel += 1) {
      const data = decoded.getChannelData(channel);
      for (let index = 0; index < data.length; index += 1) {
        mono[index] += data[index] / decoded.numberOfChannels;
      }
    }
    return { samples: mono, sampleRate: decoded.sampleRate };
  } finally {
    await context.close();
  }
}

export function sliceSamples(
  samples: Float32Array,
  sampleRate: number,
  startSeconds: number,
  endSeconds: number,
): Float32Array {
  const start = Math.max(0, Math.floor(startSeconds * sampleRate));
  const end = Math.min(samples.length, Math.ceil(endSeconds * sampleRate));
  return samples.slice(start, Math.max(start, end));
}

export function resampleLinear(
  samples: Float32Array,
  sourceSampleRate: number,
  targetSampleRate: number,
): Float32Array {
  if (!Number.isFinite(sourceSampleRate) || sourceSampleRate <= 0) {
    throw new Error("source sample rate must be positive");
  }
  if (!Number.isFinite(targetSampleRate) || targetSampleRate <= 0) {
    throw new Error("target sample rate must be positive");
  }
  if (samples.length === 0 || sourceSampleRate === targetSampleRate) {
    return samples.slice();
  }
  const outputLength = Math.max(1, Math.round((samples.length * targetSampleRate) / sourceSampleRate));
  const output = new Float32Array(outputLength);
  const sourceStep = sourceSampleRate / targetSampleRate;
  for (let index = 0; index < outputLength; index += 1) {
    const sourcePosition = Math.min(samples.length - 1, index * sourceStep);
    const left = Math.floor(sourcePosition);
    const right = Math.min(samples.length - 1, left + 1);
    const fraction = sourcePosition - left;
    output[index] = samples[left] * (1 - fraction) + samples[right] * fraction;
  }
  return output;
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${minutes}:${remainder.toFixed(1).padStart(4, "0")}`;
}

function writeAscii(view: DataView, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}
