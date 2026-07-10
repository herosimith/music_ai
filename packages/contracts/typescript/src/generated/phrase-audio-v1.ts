/* Generated from Pydantic JSON Schema. Do not edit directly. */

export type ByteLength = number;
export type CalibrationVersion = string;
export type CapturedAt = string;
export type Channels = 1;
export type Codec = "pcm_s16le" | "wav_pcm_s16le";
export type IdempotencyKey = string;
export type PhraseId = string;
export type SampleEnd = number;
export type SampleRate = number;
export type SampleStart = number;
export type SchemaVersion = "phrase-audio.v1";
export type Sequence = number;
export type SessionId = string;
export type Sha256 = string;
export type TenantId = string;

export interface PhraseAudioV1 {
  byte_length: ByteLength;
  calibration_version: CalibrationVersion;
  captured_at: CapturedAt;
  channels?: Channels;
  codec: Codec;
  idempotency_key: IdempotencyKey;
  phrase_id: PhraseId;
  sample_end: SampleEnd;
  sample_rate: SampleRate;
  sample_start: SampleStart;
  schema_version: SchemaVersion;
  sequence: Sequence;
  session_id: SessionId;
  sha256: Sha256;
  tenant_id: TenantId;
}
