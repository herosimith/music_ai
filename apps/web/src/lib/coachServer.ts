import "server-only";

import { readFileSync } from "node:fs";

import {
  ruleCoachResponse,
  type CoachEvidence,
  type CoachFallbackReason,
  type CoachResponse,
} from "./coachProtocol";

type FetchResult = Pick<Response, "status" | "text">;
type Fetcher = (input: string, init: RequestInit) => Promise<FetchResult>;

interface CoachServerOptions {
  env?: Record<string, string | undefined>;
  fetcher?: Fetcher;
  timeoutMs?: number;
}

interface CoachConfiguration {
  apiKey: string;
  endpoint: string;
  model: string;
}

const MAX_PROVIDER_RESPONSE_BYTES = 1_000_000;

export async function generateCoachPlan(
  evidence: CoachEvidence,
  options: CoachServerOptions = {},
): Promise<CoachResponse> {
  const configuration = readConfiguration(options.env ?? process.env);
  if (configuration.reason) {
    return ruleCoachResponse(evidence.fallbackMessages, configuration.reason);
  }
  const aliases =
    evidence.corrections.length > 0
      ? evidence.corrections.map((_, index) => `C${index + 1}`)
      : ["overall"];
  const request = providerRequest(evidence, aliases, configuration.value.model);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 12_000);
  try {
    const response = await (options.fetcher ?? fetch)(configuration.value.endpoint, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${configuration.value.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
      redirect: "error",
      signal: controller.signal,
    });
    if (response.status < 200 || response.status >= 300) {
      return ruleCoachResponse(evidence.fallbackMessages, "provider_unavailable");
    }
    const body = await response.text();
    if (body.length > MAX_PROVIDER_RESPONSE_BYTES) {
      return ruleCoachResponse(evidence.fallbackMessages, "invalid_response");
    }
    const messages = parseProviderMessages(JSON.parse(body), new Set(aliases));
    if (!messages) return ruleCoachResponse(evidence.fallbackMessages, "invalid_response");
    return {
      provider: "llm.responses.v1",
      model: configuration.value.model,
      usedFallback: false,
      fallbackReason: null,
      messages,
    };
  } catch {
    return ruleCoachResponse(evidence.fallbackMessages, "provider_unavailable");
  } finally {
    clearTimeout(timeout);
  }
}

function readConfiguration(
  env: Record<string, string | undefined>,
): { value: CoachConfiguration; reason?: never } | { value?: never; reason: CoachFallbackReason } {
  let apiKey = env.MUSIC_AI_COACH_API_KEY?.trim();
  if (!apiKey && env.MUSIC_AI_COACH_API_KEY_FILE) {
    try {
      apiKey = readFileSync(env.MUSIC_AI_COACH_API_KEY_FILE, "utf8").trim();
    } catch {
      return { reason: "configuration_error" };
    }
  }
  apiKey ||= env.OPENAI_API_KEY?.trim();
  if (!apiKey) return { reason: "not_configured" };
  const model = env.MUSIC_AI_COACH_MODEL?.trim() || "gpt-5.4";
  const baseUrl =
    env.MUSIC_AI_COACH_BASE_URL?.trim() || env.AI_BASE_URL?.trim() || "https://api.openai.com/v1";
  if (
    apiKey.length < 20 ||
    apiKey.length > 2_048 ||
    /\s/.test(apiKey) ||
    !/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/.test(model)
  ) {
    return { reason: "configuration_error" };
  }
  try {
    return { value: { apiKey, endpoint: responsesEndpoint(baseUrl), model } };
  } catch {
    return { reason: "configuration_error" };
  }
}

function responsesEndpoint(baseUrl: string): string {
  const url = new URL(baseUrl);
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("invalid protocol");
  if (url.username || url.password || url.search || url.hash) throw new Error("invalid coach URL");
  if (
    url.protocol === "http:" &&
    url.hostname !== "127.0.0.1" &&
    url.hostname !== "localhost" &&
    url.hostname !== "::1"
  ) {
    throw new Error("insecure coach URL");
  }
  let path = url.pathname.replace(/\/+$/, "");
  if (!path) path = "/v1";
  if (!path.endsWith("/responses")) path = `${path}/responses`;
  url.pathname = path;
  return url.toString();
}

function providerRequest(evidence: CoachEvidence, aliases: string[], model: string): object {
  const corrections = evidence.corrections.map((correction, index) => ({
    alias: aliases[index],
    end_seconds: correction.endSeconds,
    kind: correction.kind,
    severity: correction.severity,
    start_seconds: correction.startSeconds,
  }));
  return {
    model,
    input: [
      {
        role: "developer",
        content: [
          {
            type: "input_text",
            text: [
              "You are a singing practice coach. Measurements are immutable evidence.",
              "Return concise Chinese exercises only; never change, estimate, or repeat measurements.",
              "Use only the supplied correction aliases. Do not mention files, songs, users, or raw audio.",
              "Do not include Arabic digits, percentages, cents, milliseconds, frequencies, or scores.",
            ].join(" "),
          },
        ],
      },
      {
        role: "user",
        content: [
          {
            type: "input_text",
            text: JSON.stringify(
              { schema_version: evidence.schemaVersion, metrics: evidence.metrics, corrections },
              null,
              0,
            ),
          },
        ],
      },
    ],
    text: {
      format: {
        type: "json_schema",
        name: "music_ai_coach_plan",
        strict: true,
        schema: {
          type: "object",
          properties: {
            advice: {
              type: "array",
              minItems: 1,
              maxItems: 3,
              items: {
                type: "object",
                properties: {
                  correction_alias: { type: "string", enum: aliases },
                  message: { type: "string", minLength: 1, maxLength: 240 },
                },
                required: ["correction_alias", "message"],
                additionalProperties: false,
              },
            },
          },
          required: ["advice"],
          additionalProperties: false,
        },
      },
    },
    max_output_tokens: 384,
    store: false,
  };
}

function parseProviderMessages(payload: unknown, aliases: Set<string>): string[] | null {
  if (!isRecord(payload) || payload.status !== "completed" || !Array.isArray(payload.output)) {
    return null;
  }
  const texts: string[] = [];
  for (const item of payload.output) {
    if (!isRecord(item) || item.type !== "message" || !Array.isArray(item.content)) continue;
    for (const part of item.content) {
      if (!isRecord(part)) continue;
      if (part.type === "refusal" || part.refusal) return null;
      if (part.type === "output_text" && typeof part.text === "string") texts.push(part.text);
    }
  }
  if (texts.length !== 1) return null;
  let decoded: unknown;
  try {
    decoded = JSON.parse(texts[0]);
  } catch {
    return null;
  }
  if (!isRecord(decoded) || !Array.isArray(decoded.advice)) return null;
  if (decoded.advice.length < 1 || decoded.advice.length > 3) return null;
  const messages: string[] = [];
  for (const item of decoded.advice) {
    if (
      !isRecord(item) ||
      typeof item.correction_alias !== "string" ||
      !aliases.has(item.correction_alias) ||
      typeof item.message !== "string"
    ) {
      return null;
    }
    const message = item.message.trim().replace(/\s+/g, " ");
    if (
      message.length < 1 ||
      message.length > 240 ||
      /\d|%|音分|毫秒|赫兹|hz/i.test(message) ||
      messages.includes(message)
    ) {
      return null;
    }
    messages.push(message);
  }
  return messages;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
