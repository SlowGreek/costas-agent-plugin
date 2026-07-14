import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import test from "node:test";
import {
    childClientOptions,
    resolveCliLaunch,
    runtimeConnectionOptions,
} from "../extensions/ultracode/runtime-policy.mjs";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(TEST_DIR);
const STATE_ROOT = path.join(TEST_DIR, ".sdk-state");
const SDK_DIR = process.env.COPILOT_SDK_PATH;
const DIST_DIR = process.env.COPILOT_CLI_DIST_DIR;
const SEA_PATH = process.env.COPILOT_SEA_PATH;
const INSTALLED_HOME = process.env.COPILOT_INSTALLED_HOME;

async function loadSdk() {
    if (!SDK_DIR) throw new Error("COPILOT_SDK_PATH is required");
    return import(pathToFileURL(path.join(SDK_DIR, "index.js")).href);
}

async function startAndStop(label, launch) {
    const { CopilotClient, RuntimeConnection } = await loadSdk();
    const baseDirectory = path.join(STATE_ROOT, label);
    await fs.rm(baseDirectory, { recursive: true, force: true });
    await fs.mkdir(baseDirectory, { recursive: true });
    const connection = RuntimeConnection.forStdio(runtimeConnectionOptions(launch));
    const client = new CopilotClient({
        ...childClientOptions({ connection, baseDirectory }),
        workingDirectory: ROOT,
    });
    let started = false;
    try {
        await client.start();
        started = true;
    } finally {
        const errors = await client.stop();
        if (started) assert.deepEqual(errors, []);
        await fs.rm(baseDirectory, { recursive: true, force: true });
    }

}

async function waitForUltracode(session) {
    const deadline = Date.now() + 15_000;
    let latest = [];
    while (Date.now() < deadline) {
        const listed = await session.rpc.extensions.list();
        latest = listed.extensions;
        const ultracode = listed.extensions.find(
            (extension) => extension.name === "ultracode" || extension.id.endsWith(":ultracode"),
        );
        if (ultracode?.status === "running") return ultracode;
        if (ultracode?.status === "failed") {
            throw new Error(`Ultracode extension failed to start: ${JSON.stringify(ultracode)}`);
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`Ultracode extension did not reach running status: ${JSON.stringify(latest)}`);
}

test(
    "current SDK starts and stops the CLI from a regular Node extension process",
    { skip: !SDK_DIR || !DIST_DIR, timeout: 30_000 },
    async () => {
        const launch = await resolveCliLaunch({
            env: { COPILOT_CLI_DIST_DIR: DIST_DIR },
            execPath: process.execPath,
            sea: false,
        });
        assert.deepEqual(launch.args, [path.resolve(DIST_DIR, "index.js")]);
        await startAndStop("regular-node", launch);
    },
);

test(
    "current SDK starts and stops a Copilot SEA executable directly",
    { skip: !SDK_DIR || !SEA_PATH, timeout: 30_000 },
    async () => {
        const launch = await resolveCliLaunch({
            env: {},
            execPath: SEA_PATH,
            sea: true,
        });
        assert.deepEqual(launch.args, []);
        await startAndStop("sea", launch);
    },
);

test(
    "empty-mode child session authenticates without an explicit token copy",
    { skip: !SDK_DIR || !DIST_DIR, timeout: 45_000 },
    async () => {
        const sdk = await loadSdk();
        const launch = await resolveCliLaunch({
            env: { COPILOT_CLI_DIST_DIR: DIST_DIR },
            execPath: process.execPath,
            sea: false,
        });
        const baseDirectory = path.join(STATE_ROOT, "empty-auth");
        await fs.rm(baseDirectory, { recursive: true, force: true });
        await fs.mkdir(baseDirectory, { recursive: true });
        const connection = sdk.RuntimeConnection.forStdio(runtimeConnectionOptions(launch));
        const options = childClientOptions({ connection, baseDirectory });
        assert.equal("gitHubToken" in options, false);
        assert.equal("env" in options, false);
        const client = new sdk.CopilotClient({
            ...options,
            workingDirectory: ROOT,
        });
        let session;
        try {
            await client.start();
            session = await client.createSession({
                workingDirectory: ROOT,
                availableTools: ["view"],
                excludedTools: ["task", "search_code_subagent"],
                enableConfigDiscovery: false,
                onPermissionRequest: sdk.approveAll,
            });
            assert.match(session.sessionId, /\S+/);
        } finally {
            if (session) await session.disconnect();
            await client.stop();
            await fs.rm(baseDirectory, { recursive: true, force: true });
        }
    },
);

test(
    "regular Node runtime discovers the installed plugin extension and its tools",
    { skip: !SDK_DIR || !DIST_DIR || !INSTALLED_HOME, timeout: 45_000 },
    async () => {
        const sdk = await loadSdk();
        const launch = await resolveCliLaunch({
            env: { COPILOT_CLI_DIST_DIR: DIST_DIR },
            execPath: process.execPath,
            sea: false,
        });
        const baseDirectory = path.resolve(INSTALLED_HOME);
        const client = new sdk.CopilotClient({
            connection: sdk.RuntimeConnection.forStdio(runtimeConnectionOptions(launch)),
            baseDirectory,
            workingDirectory: ROOT,
            logLevel: "error",
            useLoggedInUser: true,
        });
        let session;
        try {
            await client.start();
            session = await client.createSession({
                workingDirectory: ROOT,
                enableConfigDiscovery: true,
                requestExtensions: true,
                onPermissionRequest: sdk.approveAll,
            });
            const extension = await waitForUltracode(session);
            assert.equal(extension.source, "plugin");
            await fs.access(
                path.join(
                    baseDirectory,
                    "plugin-data",
                    "costas-agent-tools",
                    "costas-agent-plugin",
                    "ultracode",
                    "runs",
                ),
            );
            await session.rpc.tools.initializeAndValidate();
            const metadata = await session.rpc.tools.getCurrentMetadata();
            const names = new Set((metadata.tools ?? []).map((tool) => tool.name));
            for (const name of [
                "ultracode_start",
                "ultracode_status",
                "ultracode_wait",
                "ultracode_cancel",
                "ultracode_resume",
                "ultracode_list",
            ]) {
                assert.ok(names.has(name), `${name} was not discovered`);
            }
        } finally {
            if (session) await session.disconnect();
            await client.stop();
        }
    },
);
