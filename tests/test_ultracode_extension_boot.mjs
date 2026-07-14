import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";
import { childClientOptions } from "../extensions/ultracode/runtime-policy.mjs";

const execFileAsync = promisify(execFile);
const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPORTER = path.join(TEST_DIR, "fixtures", "report-auth-env.mjs");

test("extension-process spawn applies the host credential blocklist", async () => {
    const parentEnvironment = {};
    for (const name of [
        "PATH",
        "Path",
        "PATHEXT",
        "SYSTEMROOT",
        "SystemRoot",
        "COMSPEC",
        "TEMP",
        "TMP",
    ]) {
        if (process.env[name] !== undefined) parentEnvironment[name] = process.env[name];
    }
    Object.assign(parentEnvironment, {
        GITHUB_TOKEN: "blocked-github-token",
        COPILOT_GITHUB_TOKEN: "blocked-copilot-token",
        GH_TOKEN: "surviving-gh-token",
    });

    const blockedByExtensionHost = new Set(["GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"]);
    const extensionEnvironment = Object.fromEntries(
        Object.entries(parentEnvironment).filter(([name]) => !blockedByExtensionHost.has(name)),
    );
    const { stdout, stderr } = await execFileAsync(process.execPath, [REPORTER], {
        cwd: TEST_DIR,
        env: extensionEnvironment,
    });

    assert.equal(stderr, "");
    assert.deepEqual(JSON.parse(stdout), {
        GITHUB_TOKEN: false,
        COPILOT_GITHUB_TOKEN: false,
        GH_TOKEN: true,
    });

    const options = childClientOptions({
        connection: { kind: "stdio" },
        baseDirectory: path.join(TEST_DIR, "state"),
    });
    const serialized = JSON.stringify(options);
    assert.doesNotMatch(serialized, /blocked-github-token|blocked-copilot-token|surviving-gh-token/);
    assert.equal("gitHubToken" in options, false);
    assert.equal("env" in options, false);
});
