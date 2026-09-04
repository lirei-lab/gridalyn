// Parse every ```mermaid fence in docs/**/*.md and README.md with the real
// Mermaid parser, and fail naming any diagram that does not compile.
//
// Why this exists as its own gate:
//
//   `mkdocs build --strict` cannot see these failures. `pymdownx.superfences`
//   only emits `<pre class="mermaid">…</pre>`; the diagram is parsed in the
//   reader's browser, so a syntax error renders as Mermaid's "Syntax error in
//   text" bomb on the published page while every build-time check stays green.
//   The instruction ledger does not see them either: it classifies mermaid
//   fences ILLUSTRATIVE ("not executable as written") and pins their sha1, so a
//   diagram that never compiled is pinned as correct-and-unchanging.
//
//   Measured 2026-08-13: 8 diagrams in the corpus, 1 of them broken since it
//   was written (`graph` used as a node id — a reserved diagram-type keyword).
//
// Why the Mermaid version is not pinned here: Material for MkDocs loads
// `mermaid@11` from a CDN, a floating major. Installing the same floating major
// is what makes this gate measure the published site rather than a frozen
// snapshot of it. If Material changes the specifier, change it here too.
//
// Usage:
//   npm install --no-save mermaid@11 jsdom
//   node tools/check_mermaid_diagrams.mjs [--root <repo>]

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

// Mermaid reaches for a DOM at import time (DOMPurify), so one must exist
// before the module is loaded. This is the only reason jsdom is a dependency.
const dom = new JSDOM("<!doctype html><html><body></body></html>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;
// Node >= 21 exposes `navigator` as a getter-only global; plain assignment
// throws TypeError there while Node 20 (CI) accepts it. Define it instead.
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
  writable: true,
});

const { default: mermaid } = await import("mermaid");

const FENCE_OPEN = "```mermaid";
const FENCE_CLOSE = "```";

// Node ids that collide with Mermaid grammar tokens. Mermaid reports these as a
// generic parse error naming the token, which does not tell an author that the
// fix is "rename the node", so the gate says it instead.
const RESERVED_NODE_IDS = new Set([
  "graph",
  "flowchart",
  "subgraph",
  "end",
  "class",
  "click",
  "style",
  "default",
  "o",
  "x",
]);

/** Resolve the repository root from `--root` or from this file's location. */
function repoRoot(argv) {
  const flag = argv.indexOf("--root");
  if (flag !== -1) {
    if (!argv[flag + 1]) {
      throw new Error("--root requires a directory argument");
    }
    return resolve(argv[flag + 1]);
  }
  return resolve(dirname(fileURLToPath(import.meta.url)), "..");
}

/** Collect every markdown file the published site is built from. */
function markdownFiles(root) {
  const found = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      if (entry === "node_modules" || entry.startsWith(".")) continue;
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) walk(path);
      else if (entry.endsWith(".md")) found.push(path);
    }
  };
  walk(join(root, "docs"));
  found.push(join(root, "README.md"));
  return found.sort();
}

/** Extract each mermaid fence with the 1-based line its content starts on. */
function mermaidBlocks(text) {
  const lines = text.split("\n");
  const blocks = [];
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() !== FENCE_OPEN) continue;
    let j = i + 1;
    while (j < lines.length && lines[j].trim() !== FENCE_CLOSE) j++;
    blocks.push({ line: i + 2, source: lines.slice(i + 1, j).join("\n") });
    i = j;
  }
  return blocks;
}

/** Name any reserved-word node id, so the remedy is in the message. */
function reservedNodeIds(source) {
  const hits = new Set();
  for (const match of source.matchAll(/([A-Za-z_][\w-]*)\s*[[({]/g)) {
    if (RESERVED_NODE_IDS.has(match[1])) hits.add(match[1]);
  }
  return [...hits];
}

const root = repoRoot(process.argv.slice(2));
const failures = [];
let total = 0;

for (const path of markdownFiles(root)) {
  const location = relative(root, path);
  for (const block of mermaidBlocks(readFileSync(path, "utf8"))) {
    total++;
    try {
      await mermaid.parse(block.source);
    } catch (error) {
      const reserved = reservedNodeIds(block.source);
      failures.push({
        where: `${location}:${block.line}`,
        detail: String(error?.message ?? error).trim(),
        remedy: reserved.length
          ? `rename the node id(s) ${reserved.join(", ")} — reserved Mermaid keyword(s)`
          : "fix the diagram source; the parser message above names the offending token",
      });
    }
  }
}

if (failures.length) {
  console.error(
    `mermaid diagrams FAILED (${failures.length} of ${total} do not compile):`,
  );
  for (const failure of failures) {
    console.error(`  ${failure.where}: ${failure.remedy}`);
    for (const line of failure.detail.split("\n")) console.error(`      ${line}`);
  }
  process.exit(1);
}

console.log(`mermaid diagrams OK (${total} compiled)`);
