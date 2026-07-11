import { generateCoachPlan } from "@/lib/coachServer";
import { parseCoachEvidence, ruleCoachResponse } from "@/lib/coachProtocol";

export const runtime = "nodejs";

const MAX_REQUEST_BYTES = 16_384;
const RATE_LIMIT_MAX = 12;
const RATE_LIMIT_MAX_KEYS = 10_000;
const RATE_LIMIT_WINDOW_MS = 60_000;
const rateLimits = new Map<string, { count: number; startedAt: number }>();

export async function POST(request: Request): Promise<Response> {
  const text = await readBoundedText(request);
  if (text === null) return json({ error: "request_too_large" }, 413);
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return json({ error: "invalid_json" }, 400);
  }
  const evidence = parseCoachEvidence(body);
  if (!evidence) return json({ error: "invalid_evidence" }, 400);
  if (!consumeRateLimit(clientKey(request))) {
    return json(ruleCoachResponse(evidence.fallbackMessages, "rate_limited"));
  }
  return json(await generateCoachPlan(evidence));
}

function consumeRateLimit(key: string): boolean {
  const now = Date.now();
  const current = rateLimits.get(key);
  if (!current && rateLimits.size >= RATE_LIMIT_MAX_KEYS) {
    for (const [candidate, value] of rateLimits) {
      if (now - value.startedAt >= RATE_LIMIT_WINDOW_MS) rateLimits.delete(candidate);
    }
    if (rateLimits.size >= RATE_LIMIT_MAX_KEYS) return false;
  }
  if (!current || now - current.startedAt >= RATE_LIMIT_WINDOW_MS) {
    rateLimits.set(key, { count: 1, startedAt: now });
    return true;
  }
  if (current.count >= RATE_LIMIT_MAX) return false;
  current.count += 1;
  return true;
}

function clientKey(request: Request): string {
  return (
    request.headers.get("x-music-ai-client-ip")?.trim() ||
    request.headers.get("x-forwarded-for")?.split(",", 1)[0]?.trim() ||
    "local"
  );
}

async function readBoundedText(request: Request): Promise<string | null> {
  const declaredLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let totalBytes = 0;
  let result = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    totalBytes += value.byteLength;
    if (totalBytes > MAX_REQUEST_BYTES) {
      await reader.cancel();
      return null;
    }
    result += decoder.decode(value, { stream: true });
  }
  return result + decoder.decode();
}

function json(value: unknown, status = 200): Response {
  return Response.json(value, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}
