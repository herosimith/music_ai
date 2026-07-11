/* Generated from Pydantic JSON Schema. Do not edit directly. */

export type CoachActionV1 =
  | LoopCoachAction
  | SlowCoachAction
  | TransposeCoachAction
  | ReferenceToneCoachAction
  | CompareTakeCoachAction
  | TextCoachAction;
export type ActionId = string;
export type ActionType = "loop";
export type EndSample = number;
export type Repetitions = number;
export type StartSample = number;
export type CoachVersion = string;
export type Locale = "zh-CN" | "en";
export type Message = string;
export type PhraseId = string;
export type ProducedAt = string;
export type Provider = string;
export type SchemaVersion = "coach-action.v1";
export type ScoreVersion = string;
export type SessionId = string;
/**
 * @maxItems 100
 */
export type SourceCorrectionIds = string[];
export type SourceScoreSha256 = string;
export type TenantId = string;
export type ActionId1 = string;
export type ActionType1 = "slow";
export type EndSample1 = number;
export type Speed = number;
export type StartSample1 = number;
export type CoachVersion1 = string;
export type Locale1 = "zh-CN" | "en";
export type Message1 = string;
export type PhraseId1 = string;
export type ProducedAt1 = string;
export type Provider1 = string;
export type SchemaVersion1 = "coach-action.v1";
export type ScoreVersion1 = string;
export type SessionId1 = string;
/**
 * @maxItems 100
 */
export type SourceCorrectionIds1 = string[];
export type SourceScoreSha2561 = string;
export type TenantId1 = string;
export type ActionId2 = string;
export type ActionType2 = "transpose";
export type Semitones = number;
export type CoachVersion2 = string;
export type Locale2 = "zh-CN" | "en";
export type Message2 = string;
export type PhraseId2 = string;
export type ProducedAt2 = string;
export type Provider2 = string;
export type SchemaVersion2 = "coach-action.v1";
export type ScoreVersion2 = string;
export type SessionId2 = string;
/**
 * @maxItems 100
 */
export type SourceCorrectionIds2 = string[];
export type SourceScoreSha2562 = string;
export type TenantId2 = string;
export type ActionId3 = string;
export type ActionType3 = "reference_tone";
export type DurationMs = number;
export type F0Hz = number;
export type CoachVersion3 = string;
export type Locale3 = "zh-CN" | "en";
export type Message3 = string;
export type PhraseId3 = string;
export type ProducedAt3 = string;
export type Provider3 = string;
export type SchemaVersion3 = "coach-action.v1";
export type ScoreVersion3 = string;
export type SessionId3 = string;
/**
 * @maxItems 100
 */
export type SourceCorrectionIds3 = string[];
export type SourceScoreSha2563 = string;
export type TenantId3 = string;
export type ActionId4 = string;
export type ActionType4 = "compare_take";
/**
 * @minItems 2
 * @maxItems 2
 */
export type TakeIds = [string, string];
export type CoachVersion4 = string;
export type Locale4 = "zh-CN" | "en";
export type Message4 = string;
export type PhraseId4 = string;
export type ProducedAt4 = string;
export type Provider4 = string;
export type SchemaVersion4 = "coach-action.v1";
export type ScoreVersion4 = string;
export type SessionId4 = string;
/**
 * @maxItems 100
 */
export type SourceCorrectionIds4 = string[];
export type SourceScoreSha2564 = string;
export type TenantId4 = string;
export type ActionId5 = string;
export type ActionType5 = "text";
export type CoachVersion5 = string;
export type Locale5 = "zh-CN" | "en";
export type Message5 = string;
export type PhraseId5 = string;
export type ProducedAt5 = string;
export type Provider5 = string;
export type SchemaVersion5 = "coach-action.v1";
export type ScoreVersion5 = string;
export type SessionId5 = string;
/**
 * @maxItems 100
 */
export type SourceCorrectionIds5 = string[];
export type SourceScoreSha2565 = string;
export type TenantId5 = string;

export interface LoopCoachAction {
  action_id: ActionId;
  action_type: ActionType;
  arguments: LoopArguments;
  coach_version: CoachVersion;
  locale: Locale;
  message: Message;
  phrase_id: PhraseId;
  produced_at: ProducedAt;
  provider: Provider;
  schema_version: SchemaVersion;
  score_version: ScoreVersion;
  session_id: SessionId;
  source_correction_ids?: SourceCorrectionIds;
  source_score_sha256: SourceScoreSha256;
  tenant_id: TenantId;
}
export interface LoopArguments {
  end_sample: EndSample;
  repetitions?: Repetitions;
  start_sample: StartSample;
}
export interface SlowCoachAction {
  action_id: ActionId1;
  action_type: ActionType1;
  arguments: SlowArguments;
  coach_version: CoachVersion1;
  locale: Locale1;
  message: Message1;
  phrase_id: PhraseId1;
  produced_at: ProducedAt1;
  provider: Provider1;
  schema_version: SchemaVersion1;
  score_version: ScoreVersion1;
  session_id: SessionId1;
  source_correction_ids?: SourceCorrectionIds1;
  source_score_sha256: SourceScoreSha2561;
  tenant_id: TenantId1;
}
export interface SlowArguments {
  end_sample: EndSample1;
  speed: Speed;
  start_sample: StartSample1;
}
export interface TransposeCoachAction {
  action_id: ActionId2;
  action_type: ActionType2;
  arguments: TransposeArguments;
  coach_version: CoachVersion2;
  locale: Locale2;
  message: Message2;
  phrase_id: PhraseId2;
  produced_at: ProducedAt2;
  provider: Provider2;
  schema_version: SchemaVersion2;
  score_version: ScoreVersion2;
  session_id: SessionId2;
  source_correction_ids?: SourceCorrectionIds2;
  source_score_sha256: SourceScoreSha2562;
  tenant_id: TenantId2;
}
export interface TransposeArguments {
  semitones: Semitones;
}
export interface ReferenceToneCoachAction {
  action_id: ActionId3;
  action_type: ActionType3;
  arguments: ReferenceToneArguments;
  coach_version: CoachVersion3;
  locale: Locale3;
  message: Message3;
  phrase_id: PhraseId3;
  produced_at: ProducedAt3;
  provider: Provider3;
  schema_version: SchemaVersion3;
  score_version: ScoreVersion3;
  session_id: SessionId3;
  source_correction_ids?: SourceCorrectionIds3;
  source_score_sha256: SourceScoreSha2563;
  tenant_id: TenantId3;
}
export interface ReferenceToneArguments {
  duration_ms: DurationMs;
  f0_hz: F0Hz;
}
export interface CompareTakeCoachAction {
  action_id: ActionId4;
  action_type: ActionType4;
  arguments: CompareTakeArguments;
  coach_version: CoachVersion4;
  locale: Locale4;
  message: Message4;
  phrase_id: PhraseId4;
  produced_at: ProducedAt4;
  provider: Provider4;
  schema_version: SchemaVersion4;
  score_version: ScoreVersion4;
  session_id: SessionId4;
  source_correction_ids?: SourceCorrectionIds4;
  source_score_sha256: SourceScoreSha2564;
  tenant_id: TenantId4;
}
export interface CompareTakeArguments {
  take_ids: TakeIds;
}
export interface TextCoachAction {
  action_id: ActionId5;
  action_type: ActionType5;
  arguments: TextArguments;
  coach_version: CoachVersion5;
  locale: Locale5;
  message: Message5;
  phrase_id: PhraseId5;
  produced_at: ProducedAt5;
  provider: Provider5;
  schema_version: SchemaVersion5;
  score_version: ScoreVersion5;
  session_id: SessionId5;
  source_correction_ids?: SourceCorrectionIds5;
  source_score_sha256: SourceScoreSha2565;
  tenant_id: TenantId5;
}
export interface TextArguments {}
