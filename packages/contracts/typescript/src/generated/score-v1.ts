/* Generated from Pydantic JSON Schema. Do not edit directly. */

export type AbstainedReason = string | null;
export type Confidence = number;
export type CorrectionId = string;
/**
 * This interface was referenced by `ScoreV1`'s JSON-Schema
 * via the `definition` "CorrectionType".
 */
export type CorrectionType =
  "sharp" | "flat" | "octave_error" | "early" | "late" | "short" | "long" | "missed" | "unstable";
export type EndSample = number;
/**
 * @minItems 1
 * @maxItems 20
 */
export type Evidence =
  | [EvidencePointer]
  | [EvidencePointer, EvidencePointer]
  | [EvidencePointer, EvidencePointer, EvidencePointer]
  | [EvidencePointer, EvidencePointer, EvidencePointer, EvidencePointer]
  | [EvidencePointer, EvidencePointer, EvidencePointer, EvidencePointer, EvidencePointer]
  | [EvidencePointer, EvidencePointer, EvidencePointer, EvidencePointer, EvidencePointer, EvidencePointer]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ]
  | [
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer,
      EvidencePointer
    ];
export type ArtifactId = string;
export type EndSample1 = number;
export type StartSample = number;
export type Confidence1 = number;
export type Coverage = number;
export type Unit = "cents" | "milliseconds" | "ratio" | "hertz" | "semitones";
export type Value = number;
export type PhraseId = string;
export type ProducedAt = string;
export type ReferenceConfidence = number;
export type SchemaVersion = "correction-event.v1";
export type ScoreVersion = string;
export type SessionId = string;
export type Severity = number;
export type StartSample1 = number;
export type TenantId = string;
/**
 * @maxItems 10000
 */
export type Corrections = CorrectionEventV1[];
export type PhraseId1 = string;
export type ProducedAt1 = string;
/**
 * This interface was referenced by `ScoreV1`'s JSON-Schema
 * via the `definition` "ReferenceSource".
 */
export type ReferenceSource = "canonical_notes" | "independent_stems" | "extracted_recording";
export type SchemaVersion1 = "score.v1";
export type ScoredCoverage = number;
export type SessionId1 = string;
export type SongId = string;
export type TenantId1 = string;
export type TransportEvidenceSha256 = string | null;
export type UserFeaturesSha256 = string | null;
export type CalibrationVersion = string;
export type ModelRelease = string;
export type PipelineVersion = string;
export type ScoreVersion1 = string;

export interface ScoreV1 {
  abstained_reason?: AbstainedReason;
  corrections?: Corrections;
  metrics?: Metrics;
  phrase_id: PhraseId1;
  produced_at: ProducedAt1;
  reference_source: ReferenceSource;
  schema_version: SchemaVersion1;
  scored_coverage: ScoredCoverage;
  session_id: SessionId1;
  song_id: SongId;
  tenant_id: TenantId1;
  transport_evidence_sha256?: TransportEvidenceSha256;
  user_features_sha256?: UserFeaturesSha256;
  versions: VersionStamp;
}
/**
 * This interface was referenced by `ScoreV1`'s JSON-Schema
 * via the `definition` "CorrectionEventV1".
 */
export interface CorrectionEventV1 {
  confidence: Confidence;
  correction_id: CorrectionId;
  correction_type: CorrectionType;
  end_sample: EndSample;
  evidence: Evidence;
  observed?: NumericMetric | null;
  phrase_id: PhraseId;
  produced_at: ProducedAt;
  reference?: NumericMetric | null;
  reference_confidence: ReferenceConfidence;
  schema_version: SchemaVersion;
  score_version: ScoreVersion;
  session_id: SessionId;
  severity: Severity;
  start_sample: StartSample1;
  tenant_id: TenantId;
}
/**
 * This interface was referenced by `ScoreV1`'s JSON-Schema
 * via the `definition` "EvidencePointer".
 */
export interface EvidencePointer {
  artifact_id: ArtifactId;
  end_sample: EndSample1;
  start_sample: StartSample;
}
/**
 * This interface was referenced by `Metrics`'s JSON-Schema definition
 * via the `patternProperty` "^[a-z][a-z0-9_.-]{1,63}$".
 *
 * This interface was referenced by `ScoreV1`'s JSON-Schema
 * via the `definition` "NumericMetric".
 */
export interface NumericMetric {
  confidence: Confidence1;
  coverage: Coverage;
  unit: Unit;
  value: Value;
}
export interface Metrics {
  [k: string]: NumericMetric;
}
/**
 * This interface was referenced by `ScoreV1`'s JSON-Schema
 * via the `definition` "VersionStamp".
 */
export interface VersionStamp {
  calibration_version: CalibrationVersion;
  model_release: ModelRelease;
  pipeline_version: PipelineVersion;
  score_version: ScoreVersion1;
}
