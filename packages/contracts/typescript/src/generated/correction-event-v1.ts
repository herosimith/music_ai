/* Generated from Pydantic JSON Schema. Do not edit directly. */

export type Confidence = number;
export type CorrectionId = string;
/**
 * This interface was referenced by `CorrectionEventV1`'s JSON-Schema
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
 * This interface was referenced by `CorrectionEventV1`'s JSON-Schema
 * via the `definition` "EvidencePointer".
 */
export interface EvidencePointer {
  artifact_id: ArtifactId;
  end_sample: EndSample1;
  start_sample: StartSample;
}
/**
 * This interface was referenced by `CorrectionEventV1`'s JSON-Schema
 * via the `definition` "NumericMetric".
 */
export interface NumericMetric {
  confidence: Confidence1;
  coverage: Coverage;
  unit: Unit;
  value: Value;
}
