import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const contractsRoot = resolve(here, "..", "..");
const schemaRoot = resolve(contractsRoot, "schemas");
const exampleRoot = resolve(contractsRoot, "examples");

function createAjv(): Ajv2020 {
  const ajv = new Ajv2020({ allErrors: true, discriminator: true, strict: true });
  addFormats(ajv);
  return ajv;
}

describe("versioned contract examples", () => {
  const schemaFiles = readdirSync(schemaRoot)
    .filter((file) => file.endsWith(".schema.json"))
    .sort();

  for (const schemaFile of schemaFiles) {
    const version = schemaFile.replace(".schema.json", "");
    it(`validates ${version}`, () => {
      const schema = JSON.parse(readFileSync(resolve(schemaRoot, schemaFile), "utf8"));
      const example = JSON.parse(readFileSync(resolve(exampleRoot, `${version}.json`), "utf8"));
      const validate = createAjv().compile(schema);
      expect(validate(example), JSON.stringify(validate.errors)).toBe(true);
    });

    it(`rejects unknown fields in ${version}`, () => {
      const schema = JSON.parse(readFileSync(resolve(schemaRoot, schemaFile), "utf8"));
      const example = JSON.parse(readFileSync(resolve(exampleRoot, `${version}.json`), "utf8"));
      const validate = createAjv().compile(schema);
      expect(validate({ ...example, unexpected: "must fail" })).toBe(false);
      expect(validate.errors?.some((error) => error.keyword === "additionalProperties")).toBe(true);
    });

    it(`requires an explicit schema version in ${version}`, () => {
      const schema = JSON.parse(readFileSync(resolve(schemaRoot, schemaFile), "utf8"));
      const example = JSON.parse(readFileSync(resolve(exampleRoot, `${version}.json`), "utf8"));
      const { schema_version: _schemaVersion, ...withoutVersion } = example;
      const validate = createAjv().compile(schema);
      expect(validate(withoutVersion)).toBe(false);
      expect(validate.errors?.some((error) => error.keyword === "required")).toBe(true);
    });
  }
});
