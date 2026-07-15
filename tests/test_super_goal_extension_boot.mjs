import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import test from "node:test";

import {
    childClientOptions,
    resolveCliLaunch,
    resolvePluginDataDir,
    runtimeConnectionOptions,
} from "../extensions/ultracode/runtime-policy.mjs";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SOURCE_ROOT = path.dirname(TEST_DIR);
const PLUGIN_ROOT = path.resolve(process.env.COPILOT_PLUGIN_ROOT || SOURCE_ROOT);
const SDK_DIR = process.env.COPILOT_SDK_PATH;
const DIST_DIR = process.env.COPILOT_CLI_DIST_DIR;

async function loadSdk() {
    if (!SDK_DIR) throw new Error("COPILOT_SDK_PATH is required");
    return import(pathToFileURL(path.join(SDK_DIR, "index.js")).href);
}

async function waitForExtension(session, name) {
    const deadline = Date.now() + 20_000;
    let latest = [];
    while (Date.now() < deadline) {
        const listed = await session.rpc.extensions.list();
        latest = listed.extensions;
        const found = latest.find((extension) => extension.name === name || extension.id.endsWith(`:${name}`));
        if (found?.status === "running") return found;
        if (found?.status === "failed") {
            throw new Error(`${name} failed to start: ${JSON.stringify(found)}`);
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`${name} did not reach running status: ${JSON.stringify(latest)}`);
}

test(
    "installed Super Goal extension opens, persists, updates, and closes its canvas",
    { skip: !SDK_DIR || !DIST_DIR, timeout: 45_000 },
    async () => {
        const sdk = await loadSdk();
        const baseDirectory = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-extension-"));
        const previousHome = process.env.COPILOT_HOME;
        const originalWarn = console.warn;
        const sdkWarnings = [];
        process.env.COPILOT_HOME = baseDirectory;
        console.warn = (...args) => sdkWarnings.push(args.map(String).join(" "));

        const launch = await resolveCliLaunch({
            env: { COPILOT_CLI_DIST_DIR: DIST_DIR },
            execPath: process.execPath,
            sea: false,
        });
        const client = new sdk.CopilotClient({
            ...childClientOptions({
                connection: sdk.RuntimeConnection.forStdio({
                    ...runtimeConnectionOptions(launch),
                    args: [...launch.args, "--plugin-dir", PLUGIN_ROOT],
                }),
                baseDirectory,
            }),
            workingDirectory: PLUGIN_ROOT,
            logLevel: "error",
        });

        let session;
        const instanceId = "super-goal-boot";
        try {
            await client.start();
            session = await client.createSession({
                workingDirectory: PLUGIN_ROOT,
                enableConfigDiscovery: false,
                requestExtensions: true,
                availableTools: ["view"],
                onPermissionRequest: sdk.approveAll,
            });

            const extension = await waitForExtension(session, "super-goal-progress");
            assert.equal(extension.source, "plugin");

            const listed = await session.rpc.canvas.list();
            const declaration = listed.canvases.find((canvas) => canvas.canvasId === "super-goal-progress");
            assert.ok(declaration, "super-goal-progress canvas was not registered");

            const openRequest = {
                canvasId: "super-goal-progress",
                instanceId,
                input: {
                    goalId: "boot-goal",
                    objective: "Prove the installed canvas works end to end",
                    criteria: [
                        { id: "open", label: "Canvas opens" },
                        { id: "update", label: "Progress updates" },
                        { id: "close", label: "Canvas closes" },
                    ],
                    maxRounds: 3,
                },
            };
            const [opened, concurrentOpen] = await Promise.all([
                session.rpc.canvas.open(openRequest),
                session.rpc.canvas.open(openRequest),
            ]);
            assert.equal(concurrentOpen.url, opened.url);
            assert.match(opened.url, /^http:\/\/127\.0\.0\.1:\d+\/$/);

            const htmlResponse = await fetch(opened.url);
            assert.equal(htmlResponse.status, 200);
            assert.match(htmlResponse.headers.get("content-security-policy") || "", /default-src 'none'/);
            assert.equal(htmlResponse.headers.get("x-content-type-options"), "nosniff");
            assert.match(await htmlResponse.text(), /id="handoff-segments"/);

            const initialResponse = await fetch(new URL("/state.json", opened.url));
            assert.equal(initialResponse.status, 200);
            const initialPayload = await initialResponse.json();
            assert.equal(initialPayload.state.progress.percent, 0);

            const updated = await session.rpc.canvas.action.invoke({
                instanceId,
                actionName: "update_progress",
                input: {
                    expectedRevision: initialPayload.state.revision,
                    status: "running",
                    criteria: [{ id: "open", status: "passed", evidence: "GET / returned 200 with CSP." }],
                },
            });
            assert.equal(updated.result.progress.percent, 33);
            assert.equal(updated.result.revision, 2);

            await assert.rejects(
                session.rpc.canvas.action.invoke({
                    instanceId,
                    actionName: "complete",
                    input: { expectedRevision: updated.result.revision, evidence: "Not all criteria are proven." },
                }),
                /criteria not yet passed|completion/i,
            );

            assert.equal((await fetch(opened.url, { method: "POST" })).status, 405);
            assert.equal((await fetch(new URL("/mutate", opened.url))).status, 404);

            const pluginDataRoot = resolvePluginDataDir({
                extensionDir: path.join(PLUGIN_ROOT, "extensions", "super-goal-progress"),
                env: { COPILOT_HOME: baseDirectory },
            });
            const statePath = path.join(pluginDataRoot, "super-goal", session.sessionId, "boot-goal.json");
            const tampered = JSON.parse(await fs.readFile(statePath, "utf8"));
            tampered.status = "completed";
            tampered.completionEvidence = null;
            tampered.completedAt = null;
            await fs.writeFile(statePath, `${JSON.stringify(tampered)}\n`, "utf8");
            const corruptResponse = await fetch(new URL("/state.json", opened.url));
            assert.equal(corruptResponse.status, 409);
            assert.deepEqual(await corruptResponse.json(), { error: "state_corrupt" });
            await assert.rejects(
                session.rpc.canvas.action.invoke({
                    instanceId,
                    actionName: "get_state",
                    input: {},
                }),
                /state_corrupt|acceptance evidence|invalid/i,
            );

            await session.rpc.canvas.close({ instanceId });
        } finally {
            if (session) {
                await session.rpc.canvas.close({ instanceId }).catch(() => {});
                await session.disconnect();
            }
            await client.stop();
            if (previousHome === undefined) delete process.env.COPILOT_HOME;
            else process.env.COPILOT_HOME = previousHome;
            console.warn = originalWarn;
            await fs.rm(baseDirectory, { recursive: true, force: true });
        }
        assert.ok(
            sdkWarnings.every((warning) => warning === "failed to deserialize session.canvas.opened payload"),
            `unexpected SDK warning: ${sdkWarnings.join(" | ")}`,
        );
    },
);
