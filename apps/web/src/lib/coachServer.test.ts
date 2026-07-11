import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { coachAnalysisFixture } from "../test/coachTestkit";
import { generateCoachPlan } from "./coachServer";
import { buildCoachEvidence } from "./coachProtocol";

const API_KEY = "coach-key-0123456789abcdef";

function completedProviderResponse(message: string) {
  return {
    status: 200,
    text: async () =>
      JSON.stringify({
        status: "completed",
        output: [
          {
            type: "message",
            content: [
              {
                type: "output_text",
                text: JSON.stringify({
                  advice: [{ correction_alias: "C1", message }],
                }),
              },
            ],
          },
        ],
      }),
  };
}

describe("coach server gateway", () => {
  const evidence = buildCoachEvidence(coachAnalysisFixture());

  it("returns an explicit rule fallback when no provider is configured", async () => {
    const result = await generateCoachPlan(evidence, { env: {} });

    expect(result).toMatchObject({
      provider: "rules.v1",
      usedFallback: true,
      fallbackReason: "not_configured",
    });
  });

  it("sends only bounded evidence with strict schema and disabled storage", async () => {
    const fetcher = vi.fn(async (input: string, init: RequestInit) => {
      expect(input).toBe("https://gateway.example/v1/responses");
      expect(init.headers).toMatchObject({ Authorization: `Bearer ${API_KEY}` });
      expect(init.redirect).toBe("error");
      const request = JSON.parse(String(init.body));
      expect(request.model).toBe("gpt-5.4");
      expect(request.store).toBe(false);
      expect(request.max_output_tokens).toBe(384);
      expect(request.text.format).toMatchObject({ type: "json_schema", strict: true });
      const providerEvidence = JSON.parse(request.input[1].content[0].text);
      expect(providerEvidence).toEqual({
        schema_version: "local-coach-evidence.v1",
        metrics: evidence.metrics,
        corrections: [
          {
            alias: "C1",
            end_seconds: 2.6,
            kind: "flat",
            severity: 0.42,
            start_seconds: 0.4,
          },
        ],
      });
      expect(JSON.stringify(providerEvidence)).not.toContain("fallbackMessages");
      return completedProviderResponse("放松下颌，再轻声滑向目标音。");
    });

    const result = await generateCoachPlan(evidence, {
      env: {
        MUSIC_AI_COACH_API_KEY: API_KEY,
        MUSIC_AI_COACH_BASE_URL: "https://gateway.example",
        MUSIC_AI_COACH_MODEL: "gpt-5.4",
      },
      fetcher,
    });

    expect(result).toEqual({
      provider: "llm.responses.v1",
      model: "gpt-5.4",
      usedFallback: false,
      fallbackReason: null,
      messages: ["放松下颌，再轻声滑向目标音。"],
    });
  });

  it("falls back when the provider is unavailable", async () => {
    const result = await generateCoachPlan(evidence, {
      env: {
        MUSIC_AI_COACH_API_KEY: API_KEY,
        MUSIC_AI_COACH_BASE_URL: "https://gateway.example/v1",
      },
      fetcher: vi.fn(async () => ({ status: 503, text: async () => "unavailable" })),
    });

    expect(result).toMatchObject({
      provider: "rules.v1",
      fallbackReason: "provider_unavailable",
    });
  });

  it("rejects advice that restates or invents measurement values", async () => {
    const result = await generateCoachPlan(evidence, {
      env: {
        MUSIC_AI_COACH_API_KEY: API_KEY,
        MUSIC_AI_COACH_BASE_URL: "https://gateway.example/v1",
      },
      fetcher: vi.fn(async () => completedProviderResponse("把音高提高五十音分。")),
    });

    expect(result).toMatchObject({ provider: "rules.v1", fallbackReason: "invalid_response" });
  });

  it("falls back when the provider refuses the request", async () => {
    const result = await generateCoachPlan(evidence, {
      env: {
        MUSIC_AI_COACH_API_KEY: API_KEY,
        MUSIC_AI_COACH_BASE_URL: "https://gateway.example/v1",
      },
      fetcher: vi.fn(async () => ({
        status: 200,
        text: async () =>
          JSON.stringify({
            status: "completed",
            output: [{ type: "message", content: [{ type: "refusal", refusal: "no" }] }],
          }),
      })),
    });

    expect(result).toMatchObject({ provider: "rules.v1", fallbackReason: "invalid_response" });
  });

  it("rejects insecure non-local provider URLs before making a request", async () => {
    const fetcher = vi.fn();
    const result = await generateCoachPlan(evidence, {
      env: {
        MUSIC_AI_COACH_API_KEY: API_KEY,
        MUSIC_AI_COACH_BASE_URL: "http://gateway.example/v1",
      },
      fetcher,
    });

    expect(result).toMatchObject({ provider: "rules.v1", fallbackReason: "configuration_error" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
