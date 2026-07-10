/* Generated from Pydantic JSON Schema. Do not edit directly. */

export type AccompanimentLeakage = number;
export type EndSample = number;
export type Ornament = boolean;
export type StartSample = number;
/**
 * @maxItems 100000
 */
export type Candidates = ReferenceRegionCandidate[];
export type DurationSamples = number;
export type F0Confidence = number;
export type F0Hz = number | null;
export type MonophonicConfidence = number;
export type SampleIndex = number;
export type Voiced = boolean;
/**
 * @maxItems 1000000
 */
export type Frames = ReferenceF0Frame[];
export type HopSamples = number;
export type ModelRelease = string;
export type PipelineVersion = string;
export type ProducedAt = string;
export type SampleRate = number;
export type SchemaVersion = "reference-f0.v1";
export type SeparationConfidence = number;
export type SongId = string;
export type SourceVocalSha256 = string;
export type TenantId = string;
export type VocalPresenceCoverage = number;

export interface ReferenceF0V1 {
  accompaniment_leakage: AccompanimentLeakage;
  candidates?: Candidates;
  duration_samples: DurationSamples;
  frames?: Frames;
  hop_samples: HopSamples;
  model_release: ModelRelease;
  pipeline_version: PipelineVersion;
  produced_at: ProducedAt;
  sample_rate: SampleRate;
  schema_version: SchemaVersion;
  separation_confidence: SeparationConfidence;
  song_id: SongId;
  source_vocal_sha256: SourceVocalSha256;
  tenant_id: TenantId;
  vocal_presence_coverage: VocalPresenceCoverage;
}
/**
 * This interface was referenced by `ReferenceF0V1`'s JSON-Schema
 * via the `definition` "ReferenceRegionCandidate".
 */
export interface ReferenceRegionCandidate {
  end_sample: EndSample;
  ornament?: Ornament;
  start_sample: StartSample;
}
/**
 * This interface was referenced by `ReferenceF0V1`'s JSON-Schema
 * via the `definition` "ReferenceF0Frame".
 */
export interface ReferenceF0Frame {
  f0_confidence: F0Confidence;
  f0_hz?: F0Hz;
  monophonic_confidence: MonophonicConfidence;
  sample_index: SampleIndex;
  voiced: Voiced;
}
