import { joinSession } from "@github/copilot-sdk/extension";
import { CopilotClient, RuntimeConnection, approveAll } from "@github/copilot-sdk";
import { Worker } from "node:worker_threads";
import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import {
    childClientOptions,
    childToolPolicy,
    resolvePluginDataDir,
    resolveCliLaunch,
    runtimeConnectionOptions,
} from "./runtime-policy.mjs";

const execFile = promisify(execFileCallback);
const EXTENSION_DIR = path.dirname(fileURLToPath(import.meta.url));
const WORKER_PATH = path.join(EXTENSION_DIR, "worker.mjs");
const ROOT_DIR = path.join(resolvePluginDataDir({ extensionDir: EXTENSION_DIR }), "ultracode");
const RUNS_DIR = path.join(ROOT_DIR, "runs");
const SDK_HOME = path.join(ROOT_DIR, "sdk");
const DEFAULT_CONCURRENCY = 8;
const MAX_CONCURRENCY = 16;
const DEFAULT_MAX_AGENTS = 100;
const HARD_MAX_AGENTS = 1_000;
const DEFAULT_TIMEOUT_MINUTES = 60;
const HARD_TIMEOUT_MINUTES = 360;
const DEFAULT_AGENT_TIMEOUT_MINUTES = 20;
const MAX_RESULT_CHARS = 30_000;

const runs = new Map();
let sdkClientPromise;
let foregroundWorkingDirectory = process.cwd();

class Semaphore {
    constructor(limit) {
        this.limit = limit;
        this.active = 0;
        this.queue = [];
    }

    async use(fn) {
        if (this.active >= this.limit) {
            await new Promise((resolve) => this.queue.push(resolve));
        }
        this.active += 1;
        try {
            return await fn();
        } finally {
            this.active -= 1;
            this.queue.shift()?.();
        }
    }
}

function clampInteger(value, fallback, min, max) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.min(max, parsed));
}

function makeRunId() {
    const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
    return `${stamp}-${crypto.randomBytes(4).toString("hex")}`;
}

function fingerprint(value) {
    return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function stateFile(runDir) {
    return path.join(runDir, "state.json");
}

async function atomicWriteJson(file, value) {
    const staging = `${file}.${process.pid}.${crypto.randomBytes(3).toString("hex")}.pending`;
    await fs.writeFile(staging, `${JSON.stringify(value, null, 2)}\n`, "utf8");
    await fs.rename(staging, file);
}

function persist(run) {
    run.persistChain = (run.persistChain ?? Promise.resolve())
        .catch(() => {})
        .then(() => atomicWriteJson(stateFile(run.dir), run.state));
    return run.persistChain;
}

function publicState(state, includeResult = true) {
    const calls = Object.values(state.agentCalls ?? {});
    const summary = {
        runId: state.runId,
        status: state.status,
        workflow: state.workflow,
        scriptPath: state.scriptPath,
        workingDirectory: state.workingDirectory,
        startedAt: state.startedAt,
        updatedAt: state.updatedAt,
        completedAt: state.completedAt ?? null,
        maxConcurrency: state.maxConcurrency,
        maxAgents: state.maxAgents,
        permissionMode: state.permissionMode,
        agents: {
            total: calls.length,
            running: calls.filter((call) => call.status === "running").length,
            completed: calls.filter((call) => call.status === "completed").length,
            failed: calls.filter((call) => call.status === "failed").length,
            cached: calls.filter((call) => call.cacheHits > 0).length,
        },
        worktrees: state.worktrees ?? [],
        error: state.error ?? null,
    };
    if (includeResult && state.result !== undefined) {
        const serialized = JSON.stringify(state.result);
        summary.result =
            serialized.length > MAX_RESULT_CHARS
                ? {
                      truncated: true,
                      path: path.join(RUNS_DIR, state.runId, "result.json"),
                      preview: serialized.slice(0, MAX_RESULT_CHARS),
                  }
                : state.result;
    }
    return summary;
}

function toolResult(value, resultType = "success") {
    return {
        resultType,
        textResultForLlm: typeof value === "string" ? value : JSON.stringify(value, null, 2),
    };
}

async function getSdkClient() {
    if (!sdkClientPromise) {
        sdkClientPromise = (async () => {
            await fs.mkdir(SDK_HOME, { recursive: true });
            const launch = await resolveCliLaunch();
            const connection = RuntimeConnection.forStdio(runtimeConnectionOptions(launch));
            const client = new CopilotClient(
                childClientOptions({
                    connection,
                    baseDirectory: SDK_HOME,
                }),
            );
            await client.start();
            return client;
        })().catch((error) => {
            sdkClientPromise = undefined;
            throw error;
        });
    }
    return sdkClientPromise;
}

function extractJson(content) {
    const trimmed = content.trim();
    const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
    return JSON.parse(fenced ? fenced[1] : trimmed);
}

function validateSchema(value, schema, at = "$") {
    if (!schema || typeof schema !== "object") return;
    if (schema.enum && !schema.enum.some((candidate) => JSON.stringify(candidate) === JSON.stringify(value))) {
        throw new Error(`${at} is not one of the allowed enum values`);
    }
    if (schema.type === "object") {
        if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${at} must be an object`);
        for (const key of schema.required ?? []) {
            if (!(key in value)) throw new Error(`${at}.${key} is required`);
        }
        for (const [key, child] of Object.entries(schema.properties ?? {})) {
            if (key in value) validateSchema(value[key], child, `${at}.${key}`);
        }
    } else if (schema.type === "array") {
        if (!Array.isArray(value)) throw new Error(`${at} must be an array`);
        value.forEach((item, index) => validateSchema(item, schema.items, `${at}[${index}]`));
    } else if (schema.type === "string" && typeof value !== "string") {
        throw new Error(`${at} must be a string`);
    } else if (schema.type === "number" && typeof value !== "number") {
        throw new Error(`${at} must be a number`);
    } else if (schema.type === "integer" && !Number.isInteger(value)) {
        throw new Error(`${at} must be an integer`);
    } else if (schema.type === "boolean" && typeof value !== "boolean") {
        throw new Error(`${at} must be a boolean`);
    } else if (schema.type === "null" && value !== null) {
        throw new Error(`${at} must be null`);
    }
}

async function prepareAgentWorkingDirectory(run, callIndex, options) {
    if (typeof options.worktree === "string" && options.worktree.trim()) {
        return path.resolve(run.state.workingDirectory, options.worktree);
    }
    if (options.worktree !== true) return run.state.workingDirectory;

    const { stdout } = await execFile("git", [
        "-C",
        run.state.workingDirectory,
        "rev-parse",
        "--show-toplevel",
    ]);
    const gitRoot = stdout.trim();
    const worktreeDir = path.join(run.dir, "worktrees", String(callIndex));
    try {
        await fs.access(worktreeDir);
    } catch {
        await fs.mkdir(path.dirname(worktreeDir), { recursive: true });
        await execFile("git", ["-C", gitRoot, "worktree", "add", "--detach", worktreeDir, "HEAD"]);
    }
    if (!run.state.worktrees.includes(worktreeDir)) run.state.worktrees.push(worktreeDir);
    return worktreeDir;
}

async function launchAgent(run, request) {
    const { callIndex, prompt, options = {} } = request;
    const key = String(callIndex);
    const callFingerprint = fingerprint({
        prompt,
        model: options.model ?? null,
        schema: options.schema ?? null,
        label: options.label ?? null,
        worktree: options.worktree ?? false,
        permissionMode: run.state.permissionMode,
    });
    const prior = run.state.agentCalls[key];

    if (prior?.status === "completed" && prior.fingerprint === callFingerprint) {
        prior.cacheHits = (prior.cacheHits ?? 0) + 1;
        await persist(run);
        return prior.result;
    }

    const distinctCalls = Object.keys(run.state.agentCalls).length;
    if (!prior && distinctCalls >= run.state.maxAgents) {
        throw new Error(`Workflow exceeded maxAgents (${run.state.maxAgents})`);
    }
    if (run.cancelled) throw new Error("Workflow cancelled");

    const call = {
        callIndex,
        fingerprint: callFingerprint,
        label: options.label ?? `agent-${callIndex}`,
        status: "running",
        model: options.model ?? null,
        startedAt: new Date().toISOString(),
        cacheHits: prior?.cacheHits ?? 0,
    };
    run.state.agentCalls[key] = call;
    run.state.updatedAt = new Date().toISOString();
    await persist(run);

    return run.semaphore.use(async () => {
        if (run.cancelled) throw new Error("Workflow cancelled");
        let childSession;
        try {
            const workingDirectory = await prepareAgentWorkingDirectory(run, callIndex, options);
            call.workingDirectory = workingDirectory;
            const schemaInstruction = options.schema
                ? `\n\nReturn ONLY valid JSON matching this JSON Schema:\n${JSON.stringify(options.schema)}`
                : "";
            const client = await getSdkClient();
            const sessionConfig = {
                workingDirectory,
                model: options.model,
                onPermissionRequest: approveAll,
                systemMessage: {
                    mode: "append",
                    content:
                        "You are an isolated worker in an Ultracode dynamic workflow. " +
                        "Do only the assigned task. Be evidence-driven and return a concise final result." +
                        schemaInstruction,
                },
                enableConfigDiscovery: false,
                ...childToolPolicy(run.state.permissionMode),
            };

            childSession = await client.createSession(sessionConfig);
            call.sessionId = childSession.sessionId;
            run.activeSessions.add(childSession);
            await persist(run);

            const timeoutMinutes = clampInteger(
                options.timeoutMinutes,
                run.state.agentTimeoutMinutes,
                1,
                120,
            );
            const response = await childSession.sendAndWait({ prompt }, timeoutMinutes * 60_000);
            const content = response?.data?.content;
            if (typeof content !== "string") throw new Error("Agent returned no final response");
            const result = options.schema ? extractJson(content) : content;
            if (options.schema) validateSchema(result, options.schema);

            call.status = "completed";
            call.completedAt = new Date().toISOString();
            call.result = result;
            run.state.updatedAt = call.completedAt;
            await persist(run);
            return result;
        } catch (error) {
            call.status = "failed";
            call.completedAt = new Date().toISOString();
            call.error = error instanceof Error ? error.message : String(error);
            run.state.updatedAt = call.completedAt;
            await persist(run);
            if (childSession) {
                try {
                    await childSession.abort();
                } catch {}
            }
            throw error;
        } finally {
            if (childSession) {
                run.activeSessions.delete(childSession);
                try {
                    await childSession.disconnect();
                } catch {}
            }
        }
    });
}

function sendAgentResult(worker, requestId, ok, value) {
    worker.postMessage(
        ok
            ? { type: "agent-result", requestId, ok: true, value }
            : {
                  type: "agent-result",
                  requestId,
                  ok: false,
                  error: value instanceof Error ? value.message : String(value),
              },
    );
}

async function abortActiveSessions(run) {
    await Promise.allSettled(
        [...run.activeSessions].map(async (session) => {
            try {
                await session.abort();
            } finally {
                await session.disconnect();
            }
        }),
    );
    run.activeSessions.clear();
}

async function finishRun(run, status, payload) {
    if (run.finished) return;
    run.finished = true;
    clearTimeout(run.timeout);
    run.worker = undefined;
    run.state.status = status;
    run.state.updatedAt = new Date().toISOString();
    run.state.completedAt = run.state.updatedAt;
    if (status === "completed") {
        run.state.result = payload ?? null;
        await atomicWriteJson(path.join(run.dir, "result.json"), run.state.result);
    } else {
        run.state.error = payload instanceof Error ? payload.stack || payload.message : String(payload);
    }
    await persist(run);
    await hostSession.log(
        status === "completed"
            ? `Ultracode run ${run.state.runId} completed`
            : `Ultracode run ${run.state.runId} ${status}: ${run.state.error}`,
        { level: status === "completed" ? "info" : "warning" },
    );
}

async function executeRun(run) {
    if (run.worker && !run.finished) return;
    run.finished = false;
    run.cancelled = false;
    run.semaphore = new Semaphore(run.state.maxConcurrency);
    run.activeSessions ??= new Set();
    run.state.status = "running";
    run.state.error = null;
    for (const call of Object.values(run.state.agentCalls)) {
        if (call.status === "running") call.status = "interrupted";
    }
    run.state.updatedAt = new Date().toISOString();
    await persist(run);

    const source = await fs.readFile(path.join(run.dir, "workflow.js"), "utf8");
    const worker = new Worker(WORKER_PATH, {
        workerData: {
            runId: run.state.runId,
            source,
            args: run.state.args,
            scriptPath: run.state.scriptPath,
        },
    });
    run.worker = worker;
    run.timeout = setTimeout(async () => {
        run.cancelled = true;
        await worker.terminate();
        await abortActiveSessions(run);
        await finishRun(run, "timed_out", `Workflow exceeded ${run.state.timeoutMinutes} minutes`);
    }, run.state.timeoutMinutes * 60_000);

    worker.on("message", (message) => {
        if (message?.type === "agent") {
            launchAgent(run, message).then(
                (value) => sendAgentResult(worker, message.requestId, true, value),
                (error) => sendAgentResult(worker, message.requestId, false, error),
            );
        } else if (message?.type === "complete") {
            finishRun(run, "completed", message.result).catch(() => {});
        } else if (message?.type === "failed") {
            finishRun(run, "failed", message.error).catch(() => {});
        }
    });
    worker.on("error", (error) => finishRun(run, "failed", error).catch(() => {}));
    worker.on("exit", (code) => {
        if (!run.finished && !run.cancelled) {
            finishRun(run, "failed", `Workflow worker exited with code ${code}`).catch(() => {});
        }
    });
}

async function createRun(args) {
    const workingDirectory = path.resolve(args.workingDirectory || foregroundWorkingDirectory);
    const scriptPath = path.resolve(workingDirectory, args.scriptPath);
    const source = await fs.readFile(scriptPath, "utf8");
    const runId = makeRunId();
    const runDir = path.join(RUNS_DIR, runId);
    await fs.mkdir(runDir, { recursive: true });
    await fs.writeFile(path.join(runDir, "workflow.js"), source, "utf8");

    const state = {
        version: 1,
        runId,
        workflow: path.basename(scriptPath),
        scriptPath,
        workingDirectory,
        args: args.args ?? {},
        status: "starting",
        permissionMode: args.permissionMode === "workspace" ? "workspace" : "read-only",
        maxConcurrency: clampInteger(args.maxConcurrency, DEFAULT_CONCURRENCY, 1, MAX_CONCURRENCY),
        maxAgents: clampInteger(args.maxAgents, DEFAULT_MAX_AGENTS, 1, HARD_MAX_AGENTS),
        timeoutMinutes: clampInteger(
            args.timeoutMinutes,
            DEFAULT_TIMEOUT_MINUTES,
            1,
            HARD_TIMEOUT_MINUTES,
        ),
        agentTimeoutMinutes: clampInteger(
            args.agentTimeoutMinutes,
            DEFAULT_AGENT_TIMEOUT_MINUTES,
            1,
            120,
        ),
        startedAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        agentCalls: {},
        worktrees: [],
    };
    const run = {
        dir: runDir,
        state,
        persistChain: Promise.resolve(),
        activeSessions: new Set(),
    };
    runs.set(runId, run);
    await persist(run);
    executeRun(run).catch((error) => finishRun(run, "failed", error));
    return run;
}

async function loadRun(runId) {
    if (runs.has(runId)) return runs.get(runId);
    const dir = path.join(RUNS_DIR, runId);
    const state = JSON.parse(await fs.readFile(stateFile(dir), "utf8"));
    const run = {
        dir,
        state,
        persistChain: Promise.resolve(),
        activeSessions: new Set(),
        finished: true,
    };
    runs.set(runId, run);
    return run;
}

async function restoreInterruptedRuns() {
    await fs.mkdir(RUNS_DIR, { recursive: true });
    const entries = await fs.readdir(RUNS_DIR, { withFileTypes: true });
    for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        try {
            const run = await loadRun(entry.name);
            if (["starting", "running"].includes(run.state.status)) {
                run.finished = false;
                executeRun(run).catch((error) => finishRun(run, "failed", error));
            }
        } catch {}
    }
}

const startParameters = {
    type: "object",
    properties: {
        scriptPath: { type: "string", description: "Path to a Claude-style workflow JavaScript file." },
        args: { type: "object", description: "JSON-serializable values exposed as the workflow `args` global." },
        workingDirectory: { type: "string", description: "Base directory for the workflow and agents." },
        permissionMode: {
            type: "string",
            enum: ["read-only", "workspace"],
            description: "read-only restricts workers to inspection tools; workspace allows normal coding tools.",
        },
        maxConcurrency: { type: "integer", minimum: 1, maximum: MAX_CONCURRENCY },
        maxAgents: { type: "integer", minimum: 1, maximum: HARD_MAX_AGENTS },
        timeoutMinutes: { type: "integer", minimum: 1, maximum: HARD_TIMEOUT_MINUTES },
        agentTimeoutMinutes: { type: "integer", minimum: 1, maximum: 120 },
    },
    required: ["scriptPath"],
};

const hostSession = await joinSession({
    hooks: {
        onSessionStart: async (input) => {
            foregroundWorkingDirectory = input.workingDirectory || foregroundWorkingDirectory;
        },
    },
    tools: [
        {
            name: "ultracode_start",
            description:
                "Start a bounded Claude-style JavaScript workflow in the background. The script may use agent(), pipeline(), args, and standard JavaScript.",
            parameters: startParameters,
            handler: async (args) => {
                try {
                    const run = await createRun(args);
                    return toolResult({
                        runId: run.state.runId,
                        status: run.state.status,
                        statePath: stateFile(run.dir),
                        message: "Workflow started in the background. Use ultracode_status or ultracode_wait.",
                    });
                } catch (error) {
                    return toolResult(error instanceof Error ? error.message : String(error), "failure");
                }
            },
        },
        {
            name: "ultracode_status",
            description: "Get current progress and final result for an Ultracode workflow run.",
            skipPermission: true,
            parameters: {
                type: "object",
                properties: { runId: { type: "string" } },
                required: ["runId"],
            },
            handler: async ({ runId }) => {
                try {
                    return toolResult(publicState((await loadRun(runId)).state));
                } catch (error) {
                    return toolResult(error instanceof Error ? error.message : String(error), "failure");
                }
            },
        },
        {
            name: "ultracode_wait",
            description: "Wait briefly for an Ultracode run to finish, then return its current status.",
            skipPermission: true,
            parameters: {
                type: "object",
                properties: {
                    runId: { type: "string" },
                    timeoutSeconds: { type: "integer", minimum: 1, maximum: 120 },
                },
                required: ["runId"],
            },
            handler: async ({ runId, timeoutSeconds }) => {
                try {
                    const run = await loadRun(runId);
                    const deadline = Date.now() + clampInteger(timeoutSeconds, 30, 1, 120) * 1_000;
                    while (Date.now() < deadline && ["starting", "running"].includes(run.state.status)) {
                        await new Promise((resolve) => setTimeout(resolve, 500));
                    }
                    return toolResult(publicState(run.state));
                } catch (error) {
                    return toolResult(error instanceof Error ? error.message : String(error), "failure");
                }
            },
        },
        {
            name: "ultracode_cancel",
            description: "Cancel a running Ultracode workflow. Completed agent results remain cached.",
            parameters: {
                type: "object",
                properties: { runId: { type: "string" } },
                required: ["runId"],
            },
            handler: async ({ runId }) => {
                try {
                    const run = await loadRun(runId);
                    run.cancelled = true;
                    if (run.worker) await run.worker.terminate();
                    await abortActiveSessions(run);
                    await finishRun(run, "cancelled", "Cancelled by user");
                    return toolResult(publicState(run.state, false));
                } catch (error) {
                    return toolResult(error instanceof Error ? error.message : String(error), "failure");
                }
            },
        },
        {
            name: "ultracode_resume",
            description: "Resume a failed, cancelled, timed-out, or interrupted run using cached completed agent results.",
            parameters: {
                type: "object",
                properties: { runId: { type: "string" } },
                required: ["runId"],
            },
            handler: async ({ runId }) => {
                try {
                    const run = await loadRun(runId);
                    if (["starting", "running"].includes(run.state.status)) {
                        return toolResult({ runId, status: run.state.status, message: "Run is already active." });
                    }
                    run.finished = false;
                    run.cancelled = false;
                    run.worker = undefined;
                    run.state.completedAt = null;
                    executeRun(run).catch((error) => finishRun(run, "failed", error));
                    return toolResult({ runId, status: "running", message: "Run resumed from cached results." });
                } catch (error) {
                    return toolResult(error instanceof Error ? error.message : String(error), "failure");
                }
            },
        },
        {
            name: "ultracode_list",
            description: "List recent Ultracode workflow runs.",
            skipPermission: true,
            parameters: {
                type: "object",
                properties: { limit: { type: "integer", minimum: 1, maximum: 50 } },
            },
            handler: async ({ limit }) => {
                try {
                    await fs.mkdir(RUNS_DIR, { recursive: true });
                    const entries = await fs.readdir(RUNS_DIR, { withFileTypes: true });
                    const states = [];
                    for (const entry of entries) {
                        if (!entry.isDirectory()) continue;
                        try {
                            const run = await loadRun(entry.name);
                            states.push(publicState(run.state, false));
                        } catch {}
                    }
                    states.sort((a, b) => String(b.startedAt).localeCompare(String(a.startedAt)));
                    return toolResult(states.slice(0, clampInteger(limit, 20, 1, 50)));
                } catch (error) {
                    return toolResult(error instanceof Error ? error.message : String(error), "failure");
                }
            },
        },
    ],
});

restoreInterruptedRuns().catch(async (error) => {
    await hostSession.log(`Ultracode could not restore interrupted runs: ${error.message}`, {
        level: "warning",
    });
});

for (const signal of ["SIGTERM", "SIGINT"]) {
    process.once(signal, async () => {
        for (const run of runs.values()) {
            if (run.worker && !run.finished) await run.worker.terminate();
            await abortActiveSessions(run);
        }
        if (sdkClientPromise) {
            try {
                const client = await sdkClientPromise;
                await client.stop();
            } catch {}
        }
        process.exit(0);
    });
}
