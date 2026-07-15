// Extension: super-goal-progress
// Live milestone, steering, and evidence dashboard for /super-goal.
//
// This file is thin SDK/HTTP wiring only. All validation, persistence, and
// business rules live in state.mjs (directly unit testable); all HTML/CSS/JS
// rendering lives in renderer.mjs. Keep it that way — extension.mjs itself
// cannot be imported by node:test because it calls joinSession() at module
// scope, which requires a live SDK connection.

import { createServer } from "node:http";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as extensionSdk from "@github/copilot-sdk/extension";
import { resolvePluginDataDir } from "../ultracode/runtime-policy.mjs";
import {
    CHILD_KINDS,
    CRITERION_STATUSES,
    EVENT_KINDS,
    HARD_MAX_ROUNDS,
    MAX_CRITERIA,
    MAX_EVIDENCE_CHARS,
    MAX_ID_CHARS,
    MAX_LABEL_CHARS,
    MAX_MESSAGE_CHARS,
    MAX_NAME_CHARS,
    MAX_OBJECTIVE_CHARS,
    MAX_REASON_CHARS,
    MAX_REF_CHARS,
    MAX_STEP_CHARS,
    MIN_CRITERIA,
    GOAL_ID_PATTERN,
    EventBroadcaster,
    applyAppendEvent,
    applyComplete,
    applyMarkBlocked,
    applyUpdateProgress,
    openGoalState,
    readStateFile,
    resolveStateLocation,
    serializeForClient,
    updateGoalState,
    validateStoredState,
    withGoalLock,
} from "./state.mjs";
import { renderShell } from "./renderer.mjs";

const HEARTBEAT_MS = 15_000;
const { joinSession } = extensionSdk;
const EXTENSION_DIR = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_DATA_ROOT = resolvePluginDataDir({ extensionDir: EXTENSION_DIR });

function canvasError(code, message) {
    if (typeof extensionSdk.CanvasError === "function") {
        return new extensionSdk.CanvasError(code, message);
    }
    const error = new Error(message);
    error.code = code;
    return error;
}

// instanceId -> { server, url, goalId, statePath, trustedRoot, sseClients, heartbeatTimer, unsubscribe }
const instanceServers = new Map();
const broadcaster = new EventBroadcaster();

function toCanvasError(error) {
    if (typeof extensionSdk.CanvasError === "function" && error instanceof extensionSdk.CanvasError) return error;
    if (error && error.name === "SuperGoalStateError") {
        return canvasError(error.code || "invalid_request", error.message);
    }
    const diagnostic = [error?.code, error?.name].find(
        (value) => typeof value === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(value),
    );
    const sourceLocation =
        typeof error?.stack === "string" ? error.stack.match(/extension\.mjs:(\d+):(\d+)/)?.slice(1).join(":") : null;
    return canvasError(
        "internal_error",
        `The Super Goal dashboard could not process that request (${diagnostic ?? "unexpected_error"}${sourceLocation ? ` at ${sourceLocation}` : ""}).`,
    );
}

function resolveInstance(ctx) {
    const entry = instanceServers.get(ctx.instanceId);
    if (!entry) {
        throw canvasError(
            "unknown_instance",
            "This canvas instance is not open. Reopen it with the same goalId to reconnect.",
        );
    }

    return entry;
}

function resolveGoalLocation(sessionId) {
    return resolveStateLocation({
        pluginDataPath: PLUGIN_DATA_ROOT,
        sessionId,
    });
}

function securityHeaders(res, { nonce } = {}) {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Referrer-Policy", "no-referrer");
    if (nonce) {
        // No frame-ancestors/X-Frame-Options: the host renders this page inside
        // its own canvas iframe, so blocking framing would break the feature.
        // Loopback-only binding is the isolation boundary; this CSP only stops
        // this page's own content from ever executing as script/style/fetching
        // cross-origin, even if a future change accidentally reflected text.
        res.setHeader(
            "Content-Security-Policy",
            [
                "default-src 'none'",
                `script-src 'nonce-${nonce}'`,
                `style-src 'nonce-${nonce}'`,
                "connect-src 'self'",
                "img-src 'self' data:",
                "base-uri 'none'",
                "form-action 'none'",
            ].join("; "),
        );
    }
}

function writeJson(res, status, body) {
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(body));
}

async function readValidatedState({ goalId, statePath, trustedRoot }) {
    const state = await readStateFile(statePath, { trustedRoot });
    return state ? validateStoredState(state, goalId) : null;
}

async function handleStateJson(res, instanceCtx) {
    try {
        const state = await withGoalLock(instanceCtx.goalId, () => readValidatedState(instanceCtx));
        if (!state) {
            writeJson(res, 404, { error: "not_found" });
            return;
        }
        writeJson(res, 200, { state: serializeForClient(state) });
    } catch (error) {
        writeJson(res, error?.code === "state_corrupt" ? 409 : 500, {
            error: error?.code === "state_corrupt" ? "state_corrupt" : "internal_error",
        });
    }
}

function handleEvents(req, res, instanceCtx) {
    const { goalId, sseClients } = instanceCtx;
    res.writeHead(200, {
        "Content-Type": "text/event-stream; charset=utf-8",
        Connection: "keep-alive",
    });
    res.write(": connected\n\n");
    sseClients.add(res);
    withGoalLock(goalId, () => readValidatedState(instanceCtx))
        .then((state) => {
            if (state) res.write(`event: state\ndata: ${JSON.stringify({ state: serializeForClient(state) })}\n\n`);
        })
        .catch((error) => {
            const code = error?.code === "state_corrupt" ? "state_corrupt" : "internal_error";
            res.write(`event: state_error\ndata: ${JSON.stringify({ error: code })}\n\n`);
            res.end();
        });
    const cleanup = () => {
        sseClients.delete(res);
    };
    req.on("close", cleanup);
    res.on("close", cleanup);
}

function handleRequest(req, res, instanceCtx) {
    if (req.method !== "GET") {
        securityHeaders(res);
        res.writeHead(405, { "Content-Type": "text/plain; charset=utf-8", Allow: "GET" });
        res.end("Method not allowed");
        return;
    }

    let pathname;
    try {
        pathname = new URL(req.url, "http://127.0.0.1").pathname;
    } catch {
        pathname = req.url;
    }

    if (pathname === "/") {
        const nonce = crypto.randomBytes(16).toString("base64");
        securityHeaders(res, { nonce });
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(renderShell({ instanceId: instanceCtx.instanceId, goalId: instanceCtx.goalId, nonce }));
        return;
    }
    if (pathname === "/state.json") {
        securityHeaders(res);
        handleStateJson(res, instanceCtx);
        return;
    }
    if (pathname === "/events") {
        securityHeaders(res);
        handleEvents(req, res, instanceCtx);
        return;
    }
    securityHeaders(res);
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Not found");
}

async function ensureServer(instanceId, goalId, statePath, trustedRoot) {
    const existing = instanceServers.get(instanceId);
    if (existing) {
        if (
            existing.goalId !== goalId ||
            existing.statePath !== statePath ||
            existing.trustedRoot !== trustedRoot
        ) {
            throw canvasError(
                "instance_goal_conflict",
                "This panel instance is already bound to another Super Goal. Open a new instance instead.",
            );
        }
        await existing.ready;
        return existing;
    }

    const sseClients = new Set();
    const entry = {
        goalId,
        statePath,
        trustedRoot,
        sseClients,
        server: null,
        url: null,
        heartbeatTimer: null,
        unsubscribe: null,
        ready: null,
    };
    entry.ready = (async () => {
        const server = createServer((req, res) => handleRequest(req, res, { instanceId, ...entry }));
        entry.server = server;
        await new Promise((resolve, reject) => {
            server.once("error", reject);
            server.listen(0, "127.0.0.1", () => resolve());
        });
        const address = server.address();
        const port = typeof address === "object" && address ? address.port : 0;
        entry.url = `http://127.0.0.1:${port}/`;
        entry.heartbeatTimer = setInterval(() => {
            for (const res of sseClients) {
                try {
                    res.write(":heartbeat\n\n");
                } catch {
                    sseClients.delete(res);
                }
            }
        }, HEARTBEAT_MS);
        entry.heartbeatTimer.unref?.();
        entry.unsubscribe = broadcaster.subscribe(goalId, (event) => {
            const payload = `event: state\ndata: ${JSON.stringify(event)}\n\n`;
            for (const res of sseClients) {
                try {
                    res.write(payload);
                } catch {
                    sseClients.delete(res);
                }
            }
        });
        return entry;
    })();
    instanceServers.set(instanceId, entry);
    try {
        await entry.ready;
        return entry;
    } catch (error) {
        if (instanceServers.get(instanceId) === entry) instanceServers.delete(instanceId);
        if (entry.server?.listening) {
            await new Promise((resolve) => entry.server.close(() => resolve()));
        }
        throw error;
    }
}

async function teardownServer(instanceId) {
    const entry = instanceServers.get(instanceId);
    if (!entry) return;
    instanceServers.delete(instanceId);
    await entry.ready.catch(() => {});
    clearInterval(entry.heartbeatTimer);
    entry.unsubscribe?.();
    for (const res of entry.sseClients) {
        try {
            res.end();
        } catch {
            // client already gone
        }
    }
    if (entry.server?.listening) {
        await new Promise((resolve) => entry.server.close(() => resolve()));
    }
}

const criteriaItemSchema = {
    type: "object",
    additionalProperties: false,
    required: ["id", "label"],
    properties: {
        id: { type: "string", minLength: 1, maxLength: MAX_ID_CHARS },
        label: { type: "string", minLength: 1, maxLength: MAX_LABEL_CHARS },
    },
};

const childSchema = {
    type: "object",
    additionalProperties: false,
    properties: {
        kind: { type: "string", enum: [...CHILD_KINDS] },
        ref: { type: "string", maxLength: MAX_REF_CHARS },
        name: { type: "string", maxLength: MAX_NAME_CHARS },
    },
};

const openInputSchema = {
    type: "object",
    additionalProperties: false,
    required: ["goalId", "objective", "criteria"],
    properties: {
        goalId: {
            type: "string",
            pattern: GOAL_ID_PATTERN.source,
            description: "Stable id for the delegated goal. Reopening the same goalId rehydrates its durable state instead of resetting it.",
        },
        objective: { type: "string", minLength: 1, maxLength: MAX_OBJECTIVE_CHARS },
        criteria: {
            type: "array",
            minItems: MIN_CRITERIA,
            maxItems: MAX_CRITERIA,
            items: criteriaItemSchema,
            description: `${MIN_CRITERIA}-${MAX_CRITERIA} falsifiable, unique acceptance criteria derived before delegation.`,
        },
        child: childSchema,
        maxRounds: { type: "integer", minimum: 1, maximum: HARD_MAX_ROUNDS },
    },
};

const criteriaUpdateSchema = {
    type: "array",
    minItems: 1,
    maxItems: MAX_CRITERIA,
    items: {
        type: "object",
        additionalProperties: false,
        required: ["id"],
        properties: {
            id: { type: "string" },
            status: { type: "string", enum: [...CRITERION_STATUSES] },
            evidence: { type: "string", maxLength: MAX_EVIDENCE_CHARS },
        },
    },
};

const updateProgressSchema = {
    type: "object",
    additionalProperties: false,
    required: ["expectedRevision"],
    properties: {
        status: { type: "string", enum: ["pending", "running", "paused", "stopped"] },
        currentStep: { type: "string", maxLength: MAX_STEP_CHARS },
        nextStep: { type: "string", maxLength: MAX_STEP_CHARS },
        child: childSchema,
        replacementReason: { type: "string", minLength: 1, maxLength: MAX_REASON_CHARS },
        handoffEvidence: { type: "string", minLength: 1, maxLength: MAX_EVIDENCE_CHARS },
        criteria: criteriaUpdateSchema,
        expectedRevision: { type: "integer", minimum: 0 },
    },
};

const appendEventSchema = {
    type: "object",
    additionalProperties: false,
    required: ["message", "expectedRevision"],
    properties: {
        message: { type: "string", minLength: 1, maxLength: MAX_MESSAGE_CHARS },
        kind: { type: "string", enum: [...EVENT_KINDS] },
        evidence: { type: "string", maxLength: MAX_EVIDENCE_CHARS },
        expectedRevision: { type: "integer", minimum: 0 },
    },
};

const completeSchema = {
    type: "object",
    additionalProperties: false,
    required: ["evidence", "expectedRevision"],
    properties: {
        evidence: { type: "string", minLength: 1, maxLength: MAX_EVIDENCE_CHARS },
        expectedRevision: { type: "integer", minimum: 0 },
    },
};

const markBlockedSchema = {
    type: "object",
    additionalProperties: false,
    required: ["reason", "expectedRevision"],
    properties: {
        reason: { type: "string", minLength: 1, maxLength: MAX_REASON_CHARS },
        evidence: { type: "string", maxLength: MAX_EVIDENCE_CHARS },
        expectedRevision: { type: "integer", minimum: 0 },
    },
};

let session;

function buildCanvas() {
    return extensionSdk.createCanvas({
            id: "super-goal-progress",
            displayName: "Super Goal Mission Control",
            description:
                "Mission-control dashboard for /super-goal: shows the delegated objective, falsifiable acceptance criteria, steering state, and evidence history for a supervised child session. Read-only viewer — all writes happen through its actions, never through the page.",
            inputSchema: openInputSchema,
            actions: [
                {
                    name: "get_state",
                    description: "Return the current durable progress state for this goal, with progress recomputed from criteria.",
                    handler: async (ctx) => {
                        const { goalId, statePath, trustedRoot } = resolveInstance(ctx);
                        try {
                            const state = await withGoalLock(goalId, () =>
                                readValidatedState({ goalId, statePath, trustedRoot }),
                            );
                            if (!state) throw canvasError("state_missing", "No durable state exists for this Super Goal.");
                            return serializeForClient(state);
                        } catch (error) {
                            throw toCanvasError(error);
                        }
                    },
                },
                {
                    name: "update_progress",
                    description:
                        "Revisioned update of status, steps, child attempt, or criterion evidence. A changed child identity consumes the single replacement and requires replacementReason plus handoffEvidence. Progress and steering rounds are server-managed.",
                    inputSchema: updateProgressSchema,
                    handler: async (ctx) => {
                        const { goalId, statePath, trustedRoot } = resolveInstance(ctx);
                        try {
                            const next = await updateGoalState(
                                statePath,
                                goalId,
                                (current) =>
                                    applyUpdateProgress(current, ctx.input ?? {}, { now: new Date().toISOString() }),
                                { trustedRoot },
                            );
                            const payload = serializeForClient(next);
                            broadcaster.publish(goalId, { state: payload });
                            return payload;
                        } catch (error) {
                            throw toCanvasError(error);
                        }
                    },
                },
                {
                    name: "append_event",
                    description: "Append a caller-authored note, steering message, or evidence entry to the goal's audit history.",
                    inputSchema: appendEventSchema,
                    handler: async (ctx) => {
                        const { goalId, statePath, trustedRoot } = resolveInstance(ctx);
                        try {
                            const next = await updateGoalState(
                                statePath,
                                goalId,
                                (current) =>
                                    applyAppendEvent(current, ctx.input ?? {}, { now: new Date().toISOString() }),
                                { trustedRoot },
                            );
                            const payload = serializeForClient(next);
                            broadcaster.publish(goalId, { state: payload });
                            return payload;
                        } catch (error) {
                            throw toCanvasError(error);
                        }
                    },
                },
                {
                    name: "complete",
                    description:
                        "Mark the goal complete. Rejected unless every criterion is already 'passed' and completion evidence is supplied — call this only after independent verification.",
                    inputSchema: completeSchema,
                    handler: async (ctx) => {
                        const { goalId, statePath, trustedRoot } = resolveInstance(ctx);
                        try {
                            const next = await updateGoalState(
                                statePath,
                                goalId,
                                (current) =>
                                    applyComplete(current, ctx.input ?? {}, { now: new Date().toISOString() }),
                                { trustedRoot },
                            );
                            const payload = serializeForClient(next);
                            broadcaster.publish(goalId, { state: payload });
                            return payload;
                        } catch (error) {
                            throw toCanvasError(error);
                        }
                    },
                },
                {
                    name: "mark_blocked",
                    description:
                        "Mark the goal blocked on a genuine product/credential/external decision, recording the reason (and optional evidence).",
                    inputSchema: markBlockedSchema,
                    handler: async (ctx) => {
                        const { goalId, statePath, trustedRoot } = resolveInstance(ctx);
                        try {
                            const next = await updateGoalState(
                                statePath,
                                goalId,
                                (current) =>
                                    applyMarkBlocked(current, ctx.input ?? {}, { now: new Date().toISOString() }),
                                { trustedRoot },
                            );
                            const payload = serializeForClient(next);
                            broadcaster.publish(goalId, { state: payload });
                            return payload;
                        } catch (error) {
                            throw toCanvasError(error);
                        }
                    },
                },
            ],
            // Opens (or rehydrates/refocuses) one dashboard instance. A brand-new
            // goalId creates durable state from `input`; an already-seen goalId
            // always rehydrates its existing file — `input` is then ignored so a
            // reopen can never reset progress already recorded.
            open: async (ctx) => {
                const input = ctx.input ?? {};
                if (typeof input.goalId !== "string") {
                    throw canvasError("invalid_input", "goalId is required to open the Super Goal dashboard");
                }
                let opened;
                try {
                    const location = resolveGoalLocation(ctx.sessionId);
                    opened = await withGoalLock(input.goalId, () =>
                        openGoalState({
                            dir: location.dir,
                            trustedRoot: location.trustedRoot,
                            goalId: input.goalId,
                            input,
                        }),
                    );
                } catch (error) {
                    throw toCanvasError(error);
                }
                let entry;
                try {
                    const location = resolveGoalLocation(ctx.sessionId);
                    entry = await ensureServer(
                        ctx.instanceId,
                        input.goalId,
                        opened.statePath,
                        location.trustedRoot,
                    );
                } catch (error) {
                    throw toCanvasError(error);
                }
                return {
                    title: `Super Goal — ${input.goalId}`,
                    url: entry.url,
                    status: opened.state.status,
                };
            },
            onClose: async (ctx) => {
                await teardownServer(ctx.instanceId);
            },
        });
}

// Canvas registration is an experimental SDK surface. Older Copilot hosts can
// still load the plugin and use /super-goal's textual supervision fallback
// rather than failing the entire extension process on a missing export.
if (typeof extensionSdk.createCanvas === "function") {
    session = await joinSession({ canvases: [buildCanvas()] });
} else {
    session = await joinSession({});
}
