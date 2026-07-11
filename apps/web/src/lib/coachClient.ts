import type { LocalAnalysis } from "./analysis";
import {
  buildCoachEvidence,
  parseCoachResponse,
  ruleCoachResponse,
  type CoachResponse,
} from "./coachProtocol";

interface CoachClientOptions {
  fetcher?: typeof fetch;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export async function requestCoach(
  analysis: LocalAnalysis,
  options: CoachClientOptions = {},
): Promise<CoachResponse> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs ?? 15_000);
  const onAbort = () => controller.abort();
  options.signal?.addEventListener("abort", onAbort, { once: true });
  if (options.signal?.aborted) controller.abort();
  try {
    const response = await (options.fetcher ?? fetch)("/api/coach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildCoachEvidence(analysis)),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("coach endpoint failed");
    const result = parseCoachResponse(await response.json());
    if (!result) throw new Error("coach endpoint returned invalid data");
    return result;
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", onAbort);
  }
}

export function clientFallbackCoach(analysis: LocalAnalysis): CoachResponse {
  return ruleCoachResponse(analysis.coachMessages, "client_unavailable");
}
