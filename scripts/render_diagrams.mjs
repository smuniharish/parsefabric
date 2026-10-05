// Render diagrams/*.mmd to docs/assets/diagrams/*.png with a pinned Mermaid CLI.
//
//   node scripts/render_diagrams.mjs
//
// Requires Node.js 22.13 or newer. Mermaid CLI drives a headless Chromium; set
// PUPPETEER_EXECUTABLE_PATH to an installed Chrome, Chromium or Edge to avoid a
// separate browser download. The script records the source and configuration
// checksums in docs/assets/diagrams/manifest.json, which the test suite uses to
// detect diagrams whose PNG no longer matches its source.

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const MERMAID_CLI = "@mermaid-js/mermaid-cli@12.0.0";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sources = join(root, "diagrams");
const output = join(root, "docs", "assets", "diagrams");
const config = join(sources, "mermaid-config.json");

// Hash text with LF line endings so checkouts that convert newlines (for
// example Git with core.autocrlf on Windows) produce the same checksums.
const sha256 = (path) =>
  createHash("sha256")
    .update(readFileSync(path, "utf8").replace(/\r\n/g, "\n"))
    .digest("hex");

const diagrams = readdirSync(sources)
  .filter((name) => name.endsWith(".mmd"))
  .sort();
if (diagrams.length === 0) {
  throw new Error(`no Mermaid sources in ${relative(root, sources)}`);
}

mkdirSync(output, { recursive: true });
for (const name of readdirSync(output)) {
  if (name.endsWith(".png") && !diagrams.includes(`${basename(name, ".png")}.mmd`)) {
    rmSync(join(output, name));
  }
}

const windows = process.platform === "win32";

// Run npm's own npx entry point with this Node binary: no shell, so arguments
// are passed exactly, on every platform.
function npx() {
  const prefix = dirname(process.execPath);
  for (const candidate of [
    join(prefix, "node_modules", "npm", "bin", "npx-cli.js"),
    join(prefix, "..", "lib", "node_modules", "npm", "bin", "npx-cli.js"),
  ]) {
    if (existsSync(candidate)) {
      return [process.execPath, [candidate]];
    }
  }
  if (windows) {
    throw new Error("npm's npx-cli.js was not found next to this Node.js installation");
  }
  return ["npx", []];
}

const [command, prefixArgs] = npx();
for (const name of diagrams) {
  const target = join(output, `${basename(name, ".mmd")}.png`);
  const result = spawnSync(
    command,
    [
      ...prefixArgs,
      "--yes",
      "--package",
      MERMAID_CLI,
      "mmdc",
      "--input",
      join(sources, name),
      "--output",
      target,
      "--configFile",
      config,
      "--backgroundColor",
      "white",
      "--scale",
      "2",
      "--quiet",
    ],
    { cwd: root, stdio: "inherit" },
  );
  if (result.status !== 0) {
    throw new Error(`rendering ${name} failed with exit code ${result.status}`);
  }
  console.log(`rendered ${relative(root, target)}`);
}

const manifest = {
  renderer: MERMAID_CLI,
  config: sha256(config),
  sources: Object.fromEntries(diagrams.map((name) => [name, sha256(join(sources, name))])),
};
writeFileSync(join(output, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`wrote ${relative(root, join(output, "manifest.json"))}`);
