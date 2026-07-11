import { describe, expect, it, vi } from "vitest";

import { coachAnalysisFixture } from "../test/coachTestkit";
import { requestCoach } from "./coachClient";

describe("coach client", () => {
  it("posts bounded evidence and accepts a validated coach response", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body.schemaVersion).toBe("local-coach-evidence.v1");
      expect(JSON.stringify(body)).not.toContain("samples");
      return {
        ok: true,
        json: async () => ({
          provider: "llm.responses.v1",
          model: "gpt-5.4",
          usedFallback: false,
          fallbackReason: null,
          messages: ["放松下颌，再轻声滑向目标音。"],
        }),
      } as Response;
    }) as typeof fetch;

    const result = await requestCoach(coachAnalysisFixture(), { fetcher, timeoutMs: 100 });

    expect(result.provider).toBe("llm.responses.v1");
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("rejects malformed endpoint output so the caller can keep local rules", async () => {
    const fetcher = vi.fn(async () => ({
      ok: true,
      json: async () => ({ provider: "unknown", messages: [] }),
    })) as unknown as typeof fetch;

    await expect(
      requestCoach(coachAnalysisFixture(), { fetcher, timeoutMs: 100 }),
    ).rejects.toThrow("invalid data");
  });

  it("aborts an in-flight request when the analysis is superseded", async () => {
    const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("cancelled", "AbortError")),
          { once: true },
        );
      }),
    ) as typeof fetch;
    const controller = new AbortController();
    const request = requestCoach(coachAnalysisFixture(), {
      fetcher,
      signal: controller.signal,
      timeoutMs: 1_000,
    });

    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });
});
