import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { Worker } from "node:worker_threads";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const WORKER_PATH = path.join(TEST_DIR, "..", "extensions", "ultracode", "worker.mjs");

function runWorkflow(source, args = {}, agentHandler = async (prompt) => `answer:${prompt}`) {
    return new Promise((resolve, reject) => {
        const worker = new Worker(WORKER_PATH, {
            workerData: {
                runId: "deterministic-test",
                source,
                args,
                scriptPath: "workflow with spaces.js",
            },
        });
        worker.on("message", async (message) => {
            if (message?.type === "agent") {
                try {
                    const value = await agentHandler(message.prompt, message.options);
                    worker.postMessage({
                        type: "agent-result",
                        requestId: message.requestId,
                        ok: true,
                        value,
                    });
                } catch (error) {
                    worker.postMessage({
                        type: "agent-result",
                        requestId: message.requestId,
                        ok: false,
                        error: error instanceof Error ? error.message : String(error),
                    });
                }
            } else if (message?.type === "complete") {
                resolve(message.result);
                await worker.terminate();
            } else if (message?.type === "failed") {
                reject(new Error(message.error));
                await worker.terminate();
            }
        });
        worker.on("error", reject);
    });
}

test("sandboxed pipeline produces a deterministic result", async () => {
    const prompts = [];
    const result = await runWorkflow(
        "return pipeline(args.items, (item) => agent(`inspect:${item}`, { label: item }));",
        { items: ["a", "b", "c"] },
        async (prompt) => {
            prompts.push(prompt);
            return prompt.toUpperCase();
        },
    );
    assert.deepEqual(prompts.sort(), ["inspect:a", "inspect:b", "inspect:c"]);
    assert.deepEqual(result, ["INSPECT:A", "INSPECT:B", "INSPECT:C"]);
});

test("workflow imports are rejected", async () => {
    await assert.rejects(
        runWorkflow('import fs from "node:fs"; return fs;'),
        /Workflow imports are disabled/,
    );
});

test("dynamic string code generation is rejected", async () => {
    await assert.rejects(
        runWorkflow('return Function("return 1")();'),
        /Code generation from strings disallowed|EvalError/,
    );
});
