/* Generated from Pydantic JSON Schema. Do not edit directly. */

export type CalibrationVersion = string;
/**
 * @minItems 1
 * @maxItems 100000
 */
export type Events = [TransportSyncV1, ...TransportSyncV1[]];
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
export type PhraseId = string;
export type ProducedAt = string;
export type SchemaVersion1 = "transport-evidence.v1";
export type SessionId1 = string;
export type TenantId1 = string;

export interface TransportEvidenceV1 {
  calibration_version: CalibrationVersion;
  events: Events;
  phrase_id: PhraseId;
  produced_at: ProducedAt;
  schema_version: SchemaVersion1;
  session_id: SessionId1;
  tenant_id: TenantId1;
}
/**
 * This interface was referenced by `TransportEvidenceV1`'s JSON-Schema
 * via the `definition` "TransportSyncV1".
 */
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
