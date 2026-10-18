import { readFile } from "node:fs/promises";
import { compile } from "json-schema-to-typescript";

const schema = JSON.parse(await readFile(new URL("../schemas/responses.json", import.meta.url), "utf8"));
const expected = await compile(schema, "PublicContracts");
const actual = await readFile(new URL("../src/contracts.ts", import.meta.url), "utf8");
if (expected.replaceAll("\r\n", "\n") !== actual.replaceAll("\r\n", "\n")) {
  console.error("Generated types are stale; run npm run generate:contracts");
  process.exitCode = 1;
}
