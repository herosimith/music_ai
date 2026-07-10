/* Generated from Pydantic JSON Schema. Do not edit directly. */

/**
 * @minItems 1
 * @maxItems 1000000
 */
export type Frames = [UserFeatureFrame, ...UserFeatureFrame[]];
export type EnergyDbfs = number;
export type F0Confidence = number;
export type F0Hz = number | null;
export type LeakageConfidence = number;
export type SampleIndex = number;
export type Voiced = boolean;
export type HopSamples = number;
export type PhraseId = string;
export type ProducedAt = string;
export type SampleRate = number;
export type SchemaVersion = "user-features.v1";
export type SessionId = string;
export type SourceAudioSha256 = string;
export type TenantId = string;
export type CalibrationVersion = string;
export type ModelRelease = string;
export type PipelineVersion = string;
export type ScoreVersion = string;

export interface UserFeaturesV1 {
  frames: Frames;
  hop_samples: HopSamples;
  phrase_id: PhraseId;
  produced_at: ProducedAt;
  sample_rate: SampleRate;
  schema_version: SchemaVersion;
  session_id: SessionId;
  source_audio_sha256: SourceAudioSha256;
  tenant_id: TenantId;
  versions: VersionStamp;
}
/**
 * This interface was referenced by `UserFeaturesV1`'s JSON-Schema
 * via the `definition` "UserFeatureFrame".
 */
export interface UserFeatureFrame {
  energy_dbfs: EnergyDbfs;
  f0_confidence: F0Confidence;
  f0_hz?: F0Hz;
  leakage_confidence: LeakageConfidence;
  sample_index: SampleIndex;
  voiced: Voiced;
}
/**
 * This interface was referenced by `UserFeaturesV1`'s JSON-Schema
 * via the `definition` "VersionStamp".
 */
export interface VersionStamp {
  calibration_version: CalibrationVersion;
  model_release: ModelRelease;
  pipeline_version: PipelineVersion;
  score_version: ScoreVersion;
}
