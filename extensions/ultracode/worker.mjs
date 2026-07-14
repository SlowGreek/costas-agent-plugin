import vm from "node:vm";
import { parentPort, workerData } from "node:worker_threads";

if (!parentPort) {
    throw new Error("Ultracode worker requires a parent port");
}

let nextRequestId = 0;
const pending = new Map();

parentPort.on("message", (message) => {
    if (message?.type !== "agent-result") return;
    const waiter = pending.get(message.requestId);
    if (!waiter) return;
    pending.delete(message.requestId);
    if (message.ok) waiter.resolve(message.value);
    else waiter.reject(new Error(message.error || "Agent failed"));
});

function agent(prompt, options = {}) {
    if (typeof prompt !== "string" || !prompt.trim()) {
        return Promise.reject(new Error("agent() requires a non-empty prompt"));
    }
    const requestId = ++nextRequestId;
    return new Promise((resolve, reject) => {
        pending.set(requestId, { resolve, reject });
        parentPort.postMessage({
            type: "agent",
            requestId,
            callIndex: requestId,
            prompt,
            options,
        });
    });
}

async function pipeline(items, callback) {
    if (!Array.isArray(items)) throw new Error("pipeline() requires an array");
    if (typeof callback !== "function") throw new Error("pipeline() requires a callback");
    return Promise.all(items.map((item, index) => callback(item, index)));
}

function normalizeSource(source) {
    if (/\bimport\s*(?:\(|[\s{*])/.test(source)) {
        throw new Error("Workflow imports are disabled; use only agent(), pipeline(), args, and standard JavaScript");
    }
    if (/\bexport\s+(?!const\s+meta\b)/.test(source)) {
        throw new Error("Only `export const meta = ...` is supported");
    }
    return source.replace(/\bexport\s+const\s+meta\s*=/, "const meta =");
}

async function main() {
    const source = normalizeSource(workerData.source);
    const safeArgs = JSON.parse(JSON.stringify(workerData.args ?? {}));
    const sandbox = vm.createContext(
        {
            agent,
            pipeline,
            args: Object.freeze(safeArgs),
        },
        {
            name: `ultracode:${workerData.runId}`,
            codeGeneration: { strings: false, wasm: false },
        },
    );

    const wrapped = `(async () => {\n"use strict";\n${source}\n})()`;
    const script = new vm.Script(wrapped, {
        filename: workerData.scriptPath,
        displayErrors: true,
    });
    const result = await script.runInContext(sandbox, {
        timeout: 2_000,
        displayErrors: true,
    });
    parentPort.postMessage({ type: "complete", result: result ?? null });
}

main().catch((error) => {
    parentPort.postMessage({
        type: "failed",
        error: error instanceof Error ? error.stack || error.message : String(error),
    });
});
