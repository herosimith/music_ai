// @vitest-environment node

import { beforeEach, describe, expect, it, vi } from "vitest";

const { generateCoachPlan } = vi.hoisted(() => ({ generateCoachPlan: vi.fn() }));
vi.mock("@/lib/coachServer", () => ({ generateCoachPlan }));

import { buildCoachEvidence } from "@/lib/coachProtocol";
import { coachAnalysisFixture } from "@/test/coachTestkit";

import { POST } from "./route";

describe("coach route", () => {
  beforeEach(() => {
    generateCoachPlan.mockReset().mockResolvedValue({
      provider: "llm.responses.v1",
      model: "gpt-5.4",
      usedFallback: false,
      fallbackReason: null,
      messages: ["保持放松，再轻声重唱这一段。"],
    });
  });

  it("rejects invalid JSON without invoking the provider", async () => {
    const response = await POST(
      new Request("http://localhost/api/coach", { method: "POST", body: "not-json" }),
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "invalid_json" });
    expect(generateCoachPlan).not.toHaveBeenCalled();
  });

  it("stops reading a request after the byte limit", async () => {
    const response = await POST(
      new Request("http://localhost/api/coach", {
        method: "POST",
        body: "x".repeat(16_385),
      }),
    );

    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({ error: "request_too_large" });
    expect(generateCoachPlan).not.toHaveBeenCalled();
  });

  it("returns a visible rule fallback after the per-client request limit", async () => {
    const body = JSON.stringify(buildCoachEvidence(coachAnalysisFixture()));
    const clientIp = `rate-test-${Date.now()}`;
    const responses: Response[] = [];
    for (let index = 0; index < 13; index += 1) {
      responses.push(
        await POST(
          new Request("http://localhost/api/coach", {
            method: "POST",
            headers: { "X-Music-AI-Client-IP": clientIp },
            body,
          }),
        ),
      );
    }

    expect(generateCoachPlan).toHaveBeenCalledTimes(12);
    expect(await responses[12].json()).toMatchObject({
      provider: "rules.v1",
      fallbackReason: "rate_limited",
    });
  });
});
