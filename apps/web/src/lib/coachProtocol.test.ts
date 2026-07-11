import { describe, expect, it } from "vitest";

import { coachAnalysisFixture } from "../test/coachTestkit";
import {
  buildCoachEvidence,
  parseCoachEvidence,
  parseCoachResponse,
  ruleCoachResponse,
} from "./coachProtocol";

describe("coach protocol", () => {
  it("builds bounded evidence without audio, transport, filenames, or correction copy", () => {
    const evidence = buildCoachEvidence(coachAnalysisFixture());
    const serialized = JSON.stringify(evidence);

    expect(evidence.schemaVersion).toBe("local-coach-evidence.v1");
    expect(evidence.corrections[0]).toEqual({
      endSeconds: 2.6,
      kind: "flat",
      severity: 0.42,
      startSeconds: 0.4,
    });
    expect(serialized).not.toContain("samples");
    expect(serialized).not.toContain("transport");
    expect(serialized).not.toContain("音高偏低");
    expect(serialized).not.toContain("中位偏差");
  });

  it("rejects non-finite or out-of-range evidence", () => {
    const evidence = buildCoachEvidence(coachAnalysisFixture());

    expect(parseCoachEvidence(evidence)).not.toBeNull();
    expect(
      parseCoachEvidence({ ...evidence, metrics: { ...evidence.metrics, confidence: Number.NaN } }),
    ).toBeNull();
    expect(
      parseCoachEvidence({
        ...evidence,
        corrections: [{ ...evidence.corrections[0], severity: 1.1 }],
      }),
    ).toBeNull();
  });

  it("accepts only internally consistent provider and fallback responses", () => {
    expect(
      parseCoachResponse({
        provider: "llm.responses.v1",
        model: "gpt-5.4",
        usedFallback: false,
        fallbackReason: null,
        messages: ["放松下颌，再轻声滑向目标音。"],
      }),
    ).not.toBeNull();
    expect(
      parseCoachResponse({
        provider: "llm.responses.v1",
        model: null,
        usedFallback: true,
        fallbackReason: "provider_unavailable",
        messages: ["invalid"],
      }),
    ).toBeNull();
    expect(
      parseCoachResponse(ruleCoachResponse(["使用规则建议。"], "provider_unavailable")),
    ).not.toBeNull();
  });
});
