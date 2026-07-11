import type { CorrectionKind, LocalAnalysis } from "./analysis";

export const COACH_EVIDENCE_SCHEMA_VERSION = "local-coach-evidence.v1" as const;

export interface CoachEvidence {
  schemaVersion: typeof COACH_EVIDENCE_SCHEMA_VERSION;
  metrics: {
    confidence: number;
    medianPitchCents: number | null;
    onsetOffsetMs: number | null;
    stabilityCents: number | null;
    voicedCoverage: number;
  };
  corrections: Array<{
    endSeconds: number;
    kind: CorrectionKind;
    severity: number;
    startSeconds: number;
  }>;
  fallbackMessages: string[];
}

export type CoachFallbackReason =
  | "client_unavailable"
  | "configuration_error"
  | "invalid_response"
  | "not_configured"
  | "provider_unavailable"
  | "rate_limited";

export interface CoachResponse {
  provider: "llm.responses.v1" | "rules.v1";
  model: string | null;
  usedFallback: boolean;
  fallbackReason: CoachFallbackReason | null;
  messages: string[];
}

const CORRECTION_KINDS = new Set<CorrectionKind>([
  "early",
  "flat",
  "insufficient",
  "late",
  "sharp",
  "unstable",
]);

export function buildCoachEvidence(analysis: LocalAnalysis): CoachEvidence {
  return {
    schemaVersion: COACH_EVIDENCE_SCHEMA_VERSION,
    metrics: {
      confidence: analysis.confidence,
      medianPitchCents: analysis.medianPitchCents,
      onsetOffsetMs: analysis.onsetOffsetMs,
      stabilityCents: analysis.stabilityCents,
      voicedCoverage: analysis.voicedCoverage,
    },
    corrections: analysis.corrections.slice(0, 8).map((correction) => ({
      endSeconds: correction.endSeconds,
      kind: correction.kind,
      severity: correction.severity,
      startSeconds: correction.startSeconds,
    })),
    fallbackMessages: analysis.coachMessages.slice(0, 3),
  };
}

export function parseCoachEvidence(value: unknown): CoachEvidence | null {
  if (!isRecord(value) || value.schemaVersion !== COACH_EVIDENCE_SCHEMA_VERSION) return null;
  const metrics = value.metrics;
  if (
    !isRecord(metrics) ||
    !inRange(metrics.confidence, 0, 1) ||
    !nullableInRange(metrics.medianPitchCents, -2_400, 2_400) ||
    !nullableInRange(metrics.onsetOffsetMs, -10_000, 10_000) ||
    !nullableInRange(metrics.stabilityCents, 0, 2_400) ||
    !inRange(metrics.voicedCoverage, 0, 1)
  ) {
    return null;
  }
  if (!Array.isArray(value.corrections) || value.corrections.length > 8) return null;
  const corrections: CoachEvidence["corrections"] = [];
  for (const correction of value.corrections) {
    if (
      !isRecord(correction) ||
      typeof correction.kind !== "string" ||
      !CORRECTION_KINDS.has(correction.kind as CorrectionKind) ||
      !inRange(correction.severity, 0, 1) ||
      !inRange(correction.startSeconds, 0, 3_600) ||
      !inRange(correction.endSeconds, correction.startSeconds as number, 3_600)
    ) {
      return null;
    }
    corrections.push({
      endSeconds: correction.endSeconds as number,
      kind: correction.kind as CorrectionKind,
      severity: correction.severity as number,
      startSeconds: correction.startSeconds as number,
    });
  }
  if (
    !Array.isArray(value.fallbackMessages) ||
    value.fallbackMessages.length < 1 ||
    value.fallbackMessages.length > 3 ||
    value.fallbackMessages.some((message) => !boundedText(message, 240))
  ) {
    return null;
  }
  return {
    schemaVersion: COACH_EVIDENCE_SCHEMA_VERSION,
    metrics: {
      confidence: metrics.confidence as number,
      medianPitchCents: metrics.medianPitchCents as number | null,
      onsetOffsetMs: metrics.onsetOffsetMs as number | null,
      stabilityCents: metrics.stabilityCents as number | null,
      voicedCoverage: metrics.voicedCoverage as number,
    },
    corrections,
    fallbackMessages: [...value.fallbackMessages] as string[],
  };
}

export function parseCoachResponse(value: unknown): CoachResponse | null {
  if (!isRecord(value) || !Array.isArray(value.messages)) return null;
  if (
    value.messages.length < 1 ||
    value.messages.length > 3 ||
    value.messages.some((message) => !boundedText(message, 240))
  ) {
    return null;
  }
  if (value.provider === "llm.responses.v1") {
    if (
      value.usedFallback !== false ||
      value.fallbackReason !== null ||
      !boundedText(value.model, 200)
    ) {
      return null;
    }
  } else if (value.provider === "rules.v1") {
    if (
      value.usedFallback !== true ||
      value.model !== null ||
      !isFallbackReason(value.fallbackReason)
    ) {
      return null;
    }
  } else {
    return null;
  }
  return {
    provider: value.provider,
    model: value.model as string | null,
    usedFallback: value.usedFallback,
    fallbackReason: value.fallbackReason as CoachFallbackReason | null,
    messages: [...value.messages] as string[],
  };
}

export function ruleCoachResponse(
  fallbackMessages: readonly string[],
  fallbackReason: CoachFallbackReason,
): CoachResponse {
  return {
    provider: "rules.v1",
    model: null,
    usedFallback: true,
    fallbackReason,
    messages: fallbackMessages.slice(0, 3),
  };
}

function boundedText(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maxLength;
}

function inRange(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= minimum && value <= maximum;
}

function nullableInRange(value: unknown, minimum: number, maximum: number): boolean {
  return value === null || inRange(value, minimum, maximum);
}

function isFallbackReason(value: unknown): value is CoachFallbackReason {
  return (
    value === "client_unavailable" ||
    value === "configuration_error" ||
    value === "invalid_response" ||
    value === "not_configured" ||
    value === "provider_unavailable" ||
    value === "rate_limited"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
