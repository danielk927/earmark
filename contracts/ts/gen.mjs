// Generates index.ts from ../schemas/*.schema.json. `--check` fails if index.ts is stale.
import { compile } from "json-schema-to-typescript";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const schemas = join(here, "..", "schemas");
const load = (f) => JSON.parse(readFileSync(join(schemas, f), "utf8"));

// One wrapper schema whose $defs reference every top-level schema and every
// named $def, so each type is emitted exactly once.
const defs = {};
const top = {
  DetectionEvent: "detection_event.schema.json",
  ObjectState: "object_state.schema.json",
  Space: "space.schema.json",
  Registry: "registry.schema.json",
  Phrases: "phrases.schema.json",
  BusMessage: "bus_message.schema.json",
};
for (const [name, file] of Object.entries(top)) defs[name] = { $ref: file };
const pascal = (s) => s.replace(/(^|_)([a-z])/g, (_, __, c) => c.toUpperCase());
for (const file of ["bus_message.schema.json", "convex_http.schema.json", "registry.schema.json"]) {
  for (const [name, def] of Object.entries(load(file).$defs ?? {})) {
    if (def.properties || def.oneOf || def.allOf) defs[pascal(name)] = { $ref: `${file}#/$defs/${name}` };
  }
}
const wrapper = { title: "EarmarkContracts", type: "object", $defs: defs, additionalProperties: false };

const ts = await compile(wrapper, "EarmarkContracts", {
  cwd: schemas,
  bannerComment:
    "/* Generated from contracts/schemas by contracts/ts/gen.mjs. Do not edit by hand. */",
  unreachableDefinitions: true,
  declareExternallyReferenced: true,
  additionalProperties: false,
  strictIndexSignatures: true,
  format: true,
});
const out = join(here, "index.ts");
if (process.argv.includes("--check")) {
  if (readFileSync(out, "utf8") !== ts) {
    console.error("contracts/ts/index.ts is stale; run `npm run gen` in contracts/ts");
    process.exit(1);
  }
} else {
  writeFileSync(out, ts);
  console.log(`wrote ${out}`);
}
