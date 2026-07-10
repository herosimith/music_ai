/* Generated from Pydantic JSON Schema. Do not edit directly. */

/**
 * @minItems 1
 * @maxItems 30
 */
export type Artifacts = [ArtifactPointer, ...ArtifactPointer[]];
export type ArtifactId = string;
export type Kind = "source" | "vocal" | "accompaniment" | "f0" | "alignment" | "notes";
export type ModelRelease = string | null;
export type Sha256 = string;
export type DurationSamples = number;
/**
 * This interface was referenced by `SongManifestV1`'s JSON-Schema
 * via the `definition` "GateStatus".
 */
export type GateStatus = "accepted" | "practice_only" | "rejected";
export type ProducedAt = string;
export type Code = string;
/**
 * @maxItems 20
 */
export type Evidence =
  | []
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
export type ArtifactId1 = string;
export type EndSample = number;
export type StartSample = number;
export type MessageKey = string;
export type Severity = "info" | "warning" | "blocking";
/**
 * @maxItems 100
 */
export type QualityIssues = QualityIssue[];
/**
 * This interface was referenced by `SongManifestV1`'s JSON-Schema
 * via the `definition` "ReferenceSource".
 */
export type ReferenceSource = "canonical_notes" | "independent_stems" | "extracted_recording";
export type RightsBasis = string;
export type SampleRate = number;
export type SchemaVersion = "song-manifest.v1";
export type EndSample1 = number;
export type MonophonicConfidence = number;
export type Ornament = boolean;
export type ReferenceConfidence = number;
export type RegionId = string;
export type StartSample1 = number;
export type TargetF0Hz = number;
/**
 * @maxItems 100000
 */
export type ScorableRegions = ScorableRegion[];
export type ScorableVocalCoverage = number;
export type SongId = string;
export type SourceSha256 = string;
export type TenantId = string;
export type CalibrationVersion = string;
export type ModelRelease1 = string;
export type PipelineVersion = string;
export type ScoreVersion = string;

export interface SongManifestV1 {
  artifacts: Artifacts;
  duration_samples: DurationSamples;
  gate_status: GateStatus;
  produced_at: ProducedAt;
  quality_issues?: QualityIssues;
  reference_source: ReferenceSource;
  rights_basis: RightsBasis;
  sample_rate: SampleRate;
  schema_version: SchemaVersion;
  scorable_regions?: ScorableRegions;
  scorable_vocal_coverage: ScorableVocalCoverage;
  song_id: SongId;
  source_sha256: SourceSha256;
  tenant_id: TenantId;
  versions: VersionStamp;
}
/**
 * This interface was referenced by `SongManifestV1`'s JSON-Schema
 * via the `definition` "ArtifactPointer".
 */
export interface ArtifactPointer {
  artifact_id: ArtifactId;
  kind: Kind;
  model_release?: ModelRelease;
  sha256: Sha256;
}
/**
 * This interface was referenced by `SongManifestV1`'s JSON-Schema
 * via the `definition` "QualityIssue".
 */
export interface QualityIssue {
  code: Code;
  evidence?: Evidence;
  message_key: MessageKey;
  severity: Severity;
}
/**
 * This interface was referenced by `SongManifestV1`'s JSON-Schema
 * via the `definition` "EvidencePointer".
 */
export interface EvidencePointer {
  artifact_id: ArtifactId1;
  end_sample: EndSample;
  start_sample: StartSample;
}
/**
 * This interface was referenced by `SongManifestV1`'s JSON-Schema
 * via the `definition` "ScorableRegion".
 */
export interface ScorableRegion {
  end_sample: EndSample1;
  monophonic_confidence: MonophonicConfidence;
  ornament?: Ornament;
  reference_confidence: ReferenceConfidence;
  region_id: RegionId;
  start_sample: StartSample1;
  target_f0_hz: TargetF0Hz;
}
/**
 * This interface was referenced by `SongManifestV1`'s JSON-Schema
 * via the `definition` "VersionStamp".
 */
export interface VersionStamp {
  calibration_version: CalibrationVersion;
  model_release: ModelRelease1;
  pipeline_version: PipelineVersion;
  score_version: ScoreVersion;
}
