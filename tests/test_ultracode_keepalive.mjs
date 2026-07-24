import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const EXTENSION = path.join(TEST_DIR, "..", "extensions", "ultracode", "extension.mjs");

test("ultracode holds the event loop open after registering tools", async () => {
    const source = await readFile(EXTENSION, "utf8");

    // A referenced timer handle is what stops Node from draining the event loop
    // and exiting 0 seconds after joinSession() registers the ultracode_* tools.
    assert.match(source, /const keepAlive = setInterval\(/);
    assert.doesNotMatch(source, /keepAlive\.unref/);
    assert.match(source, /clearInterval\(keepAlive\)/);
});

test("a referenced setInterval actually keeps a node process alive", async () => {
    const { execFile } = await import("node:child_process");
    const { promisify } = await import("node:util");
    const execFileAsync = promisify(execFile);

    const started = Date.now();
    await execFileAsync(process.execPath, [
        "-e",
        "const t=setInterval(()=>{},15000); setTimeout(()=>{clearInterval(t)},1500);",
    ]);
    assert.ok(Date.now() - started >= 1400, "process exited before its keep-alive timer was cleared");
});
