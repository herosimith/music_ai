/* Generated from Pydantic JSON Schema. Do not edit directly. */

export type CapturedAt = string;
export type DriftPpm = number;
export type MicrophoneSampleIndex = number;
export type PlayheadSamples = number;
export type Revision = number;
export type SampleRate = number;
export type SchemaVersion = "transport.v1";
export type Seq = number;
export type SessionId = string;
export type TenantId = string;

export interface TransportSyncV1 {
  captured_at: CapturedAt;
  drift_ppm: DriftPpm;
  microphone_sample_index: MicrophoneSampleIndex;
  playhead_samples: PlayheadSamples;
  revision: Revision;
  sample_rate: SampleRate;
  schema_version: SchemaVersion;
  seq: Seq;
  session_id: SessionId;
  tenant_id: TenantId;
}
