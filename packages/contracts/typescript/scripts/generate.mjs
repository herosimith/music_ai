import { readdir, mkdir, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compileFromFile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(here, "..");
const schemaRoot = resolve(packageRoot, "..", "schemas");
const outputRoot = resolve(packageRoot, "src", "generated");
const topLevelTypes = {
  "coach-action-v1": "CoachActionV1",
  "correction-event-v1": "CorrectionEventV1",
  "phrase-audio-v1": "PhraseAudioV1",
  "reference-f0-v1": "ReferenceF0V1",
  "score-v1": "ScoreV1",
  "song-manifest-v1": "SongManifestV1",
  "transport-v1": "TransportSyncV1",
  "transport-evidence-v1": "TransportEvidenceV1",
  "user-features-v1": "UserFeaturesV1",
};

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
const files = (await readdir(schemaRoot)).filter((file) => file.endsWith(".schema.json")).sort();
const exports = [];

for (const file of files) {
  const outputName = basename(file, ".schema.json").replaceAll(".", "-");
  const outputFile = join(outputRoot, `${outputName}.ts`);
  const source = await compileFromFile(join(schemaRoot, file), {
    bannerComment: "/* Generated from Pydantic JSON Schema. Do not edit directly. */",
    style: { singleQuote: false },
    unreachableDefinitions: true,
  });
  await writeFile(outputFile, source, "utf8");
  const topLevelType = topLevelTypes[outputName];
  if (!topLevelType) {
    throw new Error(`No top-level TypeScript export configured for ${outputName}`);
  }
  exports.push(`export type { ${topLevelType} } from "./${outputName}.js";`);
}

await writeFile(join(outputRoot, "index.ts"), `${exports.join("\n")}\n`, "utf8");
