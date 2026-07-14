import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";
import {
    AGENT_CONTROL_TOOLS,
    WORKSPACE_EXCLUDED_TOOLS,
    childClientOptions,
    childToolPolicy,
    resolveCliLaunch,
    resolvePluginDataDir,
    runtimeConnectionOptions,
} from "../extensions/ultracode/runtime-policy.mjs";

const execFileAsync = promisify(execFile);
const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const DIST_DIR = path.join(TEST_DIR, "fixtures", "runtime path with spaces");
const CLI_ENTRY = path.join(DIST_DIR, "index.js");

test("SEA extension processes launch the Copilot executable directly", async () => {
    const launch = await resolveCliLaunch({
        env: {},
        execPath: process.execPath,
        sea: true,
    });
    assert.deepEqual(launch, {
        path: path.resolve(process.execPath),
        args: [],
        source: "sea",
    });
});

test("regular Node extension processes launch the extracted CLI entry with Node", async () => {
    const launch = await resolveCliLaunch({
        env: { COPILOT_CLI_DIST_DIR: DIST_DIR },
        execPath: process.execPath,
        sea: false,
    });
    assert.deepEqual(launch, {
        path: path.resolve(process.execPath),
        args: [CLI_ENTRY],
        source: "node-dist",
    });
    assert.deepEqual(runtimeConnectionOptions(launch), {
        path: path.resolve(process.execPath),
        args: [CLI_ENTRY],
    });
});

test("an explicit usable COPILOT_CLI_PATH takes precedence", async () => {
    const launch = await resolveCliLaunch({
        env: {
            COPILOT_CLI_PATH: CLI_ENTRY,
            COPILOT_CLI_DIST_DIR: path.join(TEST_DIR, "does-not-matter"),
        },
        execPath: path.join(TEST_DIR, "not-node"),
        sea: false,
    });
    assert.deepEqual(launch, {
        path: CLI_ENTRY,
        args: [],
        source: "COPILOT_CLI_PATH",
    });
});

test("an invalid explicit COPILOT_CLI_PATH fails clearly", async () => {
    await assert.rejects(
        resolveCliLaunch({
            env: {
                COPILOT_CLI_PATH: path.join(TEST_DIR, "missing copilot"),
                COPILOT_CLI_DIST_DIR: DIST_DIR,
            },
            execPath: process.execPath,
            sea: false,
        }),
        /COPILOT_CLI_PATH is not a usable Copilot CLI file/,
    );
});

test("regular Node launch uses argv, preserving spaces and shell metacharacters", async () => {
    const launch = await resolveCliLaunch({
        env: { COPILOT_CLI_DIST_DIR: DIST_DIR },
        execPath: process.execPath,
        sea: false,
    });
    const literal = "$(touch should-not-exist); value with spaces";
    const { stdout } = await execFileAsync(launch.path, [...launch.args, literal], {
        cwd: TEST_DIR,
    });
    assert.deepEqual(JSON.parse(stdout), [literal]);
});

test("client auth relies on inherited GH_TOKEN or gh auth without copying a secret", () => {
    const connection = { kind: "stdio" };
    const options = childClientOptions({
        connection,
        baseDirectory: path.join(TEST_DIR, "sdk state"),
    });

    assert.equal(options.mode, "empty");
    assert.equal(options.useLoggedInUser, true);
    assert.equal("gitHubToken" in options, false);
    assert.equal("env" in options, false);
});

test("plugin data resolution matches marketplace and direct PluginManager layouts", () => {
    const volumeRoot = path.parse(process.cwd()).root;
    const installedRoot = path.join(volumeRoot, "home");
    const userRoot = path.join(volumeRoot, "users", "example");
    assert.equal(
        resolvePluginDataDir({
            extensionDir: path.join(
                installedRoot,
                "installed-plugins",
                "market",
                "plugin",
                "extensions",
                "ultracode",
            ),
            env: {},
            home: userRoot,
        }),
        path.join(installedRoot, "plugin-data", "market", "plugin"),
    );
    assert.equal(
        resolvePluginDataDir({
            extensionDir: path.join(
                installedRoot,
                "installed-plugins",
                "_direct",
                "source-hash",
                "extensions",
                "ultracode",
            ),
            env: {},
            home: userRoot,
        }),
        path.join(installedRoot, "plugin-data", "_direct", "costas-agent-plugin"),
    );
    assert.equal(
        resolvePluginDataDir({
            extensionDir: path.join(volumeRoot, "source", "plugin", "extensions", "ultracode"),
            env: { COPILOT_HOME: path.join(volumeRoot, "isolated", "home") },
            home: userRoot,
        }),
        path.join(volumeRoot, "isolated", "home", "plugin-data", "_direct", "costas-agent-plugin"),
    );
    assert.equal(
        resolvePluginDataDir({
            extensionDir: path.join(volumeRoot, "source", "plugin", "extensions", "ultracode"),
            env: { COPILOT_PLUGIN_DATA: path.join(volumeRoot, "explicit", "plugin data") },
            home: userRoot,
        }),
        path.join(volumeRoot, "explicit", "plugin data"),
    );
});

test("workspace workers cannot recursively create or manage agents", () => {
    const policy = childToolPolicy("workspace");
    assert.ok(policy.availableTools.includes("builtin:*"));
    assert.ok(policy.excludedTools.includes("task"));
    assert.ok(policy.excludedTools.includes("search_code_subagent"));
    for (const tool of AGENT_CONTROL_TOOLS) {
        assert.ok(policy.excludedTools.includes(tool), `${tool} must be excluded`);
    }
    assert.deepEqual(policy.excludedTools, [...WORKSPACE_EXCLUDED_TOOLS]);
});

test("read-only workers do not gain delegation through the search allowlist", () => {
    const policy = childToolPolicy("read-only");
    assert.ok(policy.availableTools.includes("view"));
    assert.ok(policy.availableTools.includes("grep"));
    assert.equal(policy.availableTools.includes("task"), false);
    assert.equal(policy.availableTools.includes("search_code_subagent"), false);
    assert.ok(policy.excludedTools.includes("task"));
    assert.ok(policy.excludedTools.includes("search_code_subagent"));
});

test("fixture files used by launch tests are real readable files", async () => {
    assert.equal((await stat(CLI_ENTRY)).isFile(), true);
    await access(CLI_ENTRY);
    assert.match(await readFile(CLI_ENTRY, "utf8"), /process\.argv/);
});
