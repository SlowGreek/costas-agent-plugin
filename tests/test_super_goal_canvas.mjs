import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
    EventBroadcaster,
    MAX_HISTORY_ENTRIES,
    MAX_STATE_BYTES,
    SuperGoalStateError,
    applyAppendEvent,
    applyComplete,
    applyMarkBlocked,
    applyUpdateProgress,
    computeProgress,
    createInitialState,
    openGoalState,
    readStateFile,
    resolveStateDir,
    resolveStatePath,
    updateGoalState,
    validateStoredState,
    writeStateFileAtomic,
} from "../extensions/super-goal-progress/state.mjs";
import { escapeHtml, renderShell } from "../extensions/super-goal-progress/renderer.mjs";

const CRITERIA = [
    { id: "behavior", label: "Required behavior works" },
    { id: "tests", label: "Authoritative tests pass" },
    { id: "review", label: "Independent review is clear" },
];
const NOW = "2026-07-15T12:00:00.000Z";

function initial(overrides = {}) {
    return createInitialState({
        goalId: "sg-test",
        objective: "Ship the supervised objective",
        criteria: CRITERIA,
        maxRounds: 4,
        now: NOW,
        ...overrides,
    });
}

function update(state, patch, options) {
    return applyUpdateProgress(state, { expectedRevision: state.revision, ...patch }, options);
}

function append(state, input, options) {
    return applyAppendEvent(state, { expectedRevision: state.revision, ...input }, options);
}

function complete(state, input, options) {
    return applyComplete(state, { expectedRevision: state.revision, ...input }, options);
}

function block(state, input, options) {
    return applyMarkBlocked(state, { expectedRevision: state.revision, ...input }, options);
}

function expectStateError(fn, code) {
    assert.throws(fn, (error) => error instanceof SuperGoalStateError && error.code === code);
}

test("goal ids and acceptance checklist shape reject traversal and ambiguity", () => {
    for (const goalId of ["../escape", ".hidden", "space id", "a/b", "a\\b", ""]) {
        expectStateError(() => initial({ goalId }), "invalid_goal_id");
    }
    expectStateError(() => initial({ criteria: CRITERIA.slice(0, 2) }), "invalid_criteria_count");
    expectStateError(
        () =>
            initial({
                criteria: [
                    ...CRITERIA,
                    { id: "TESTS", label: "A different label with a duplicate id" },
                ],
            }),
        "duplicate_criteria",
    );
    expectStateError(
        () =>
            initial({
                criteria: [
                    ...CRITERIA,
                    { id: "extra", label: "authoritative tests pass" },
                ],
            }),
        "duplicate_criteria",
    );
});

test("progress is derived only from passed criteria and passing requires evidence", () => {
    let state = initial();
    assert.deepEqual(computeProgress(state.criteria), { passedCount: 0, totalCount: 3, percent: 0 });

    expectStateError(
        () => update(state, { criteria: [{ id: "behavior", status: "passed" }] }),
        "missing_evidence",
    );
    state = update(
        state,
        {
            status: "running",
            criteria: [{ id: "behavior", status: "passed", evidence: "Focused behavior test passed." }],
        },
        { now: "2026-07-15T12:01:00.000Z" },
    );
    assert.deepEqual(state.progress, { passedCount: 1, totalCount: 3, percent: 33 });

    state = append(
        state,
        { kind: "steer", message: "Asked the child to add missing coverage." },
        { now: "2026-07-15T12:02:00.000Z" },
    );
    assert.deepEqual(state.progress, { passedCount: 1, totalCount: 3, percent: 33 });
    assert.equal(state.round, 1);
});

test("dedicated completion and blocked actions cannot be bypassed", () => {
    const state = initial();
    expectStateError(() => update(state, { status: "completed" }), "completion_rejected");
    expectStateError(() => update(state, { status: "blocked" }), "invalid_transition");
    expectStateError(() => complete(state, { evidence: "Child said done." }), "completion_rejected");

    const blocked = block(
        state,
        { reason: "A product decision is required.", evidence: "Two valid behaviors remain." },
        { now: "2026-07-15T12:03:00.000Z" },
    );
    assert.equal(blocked.status, "blocked");
    assert.match(blocked.blockedReason, /product decision/i);

    const resumed = update(
        blocked,
        { status: "running" },
        { now: "2026-07-15T12:04:00.000Z" },
    );
    assert.equal(resumed.blockedReason, null);
    expectStateError(() => update(resumed, { round: 5 }), "invalid_field");
});

test("child replacement is durable, handoff-gated, and limited to one", () => {
    let state = initial();
    state = update(state, {
        child: { kind: "project_session", ref: "session-one", name: "First worker" },
    });
    assert.equal(state.childAttempts.length, 1);
    assert.equal(state.replacementsUsed, 0);

    state = update(state, {
        child: { kind: "project_session", ref: "session-one", name: "Renamed first worker" },
    });
    assert.equal(state.childAttempts.length, 1);
    assert.equal(state.childAttempts[0].child.name, "Renamed first worker");

    expectStateError(
        () =>
            update(state, {
                child: { kind: "project_session", ref: "session-two", name: "Replacement" },
            }),
        "missing_field",
    );
    state = update(state, {
        child: { kind: "project_session", ref: "session-two", name: "Replacement" },
        replacementReason: "The first child session became unrecoverable.",
        handoffEvidence: "No useful uncommitted changes; committed branch state was inspected.",
    });
    assert.equal(state.childAttempts.length, 2);
    assert.equal(state.replacementsUsed, 1);
    assert.equal(state.childAttempts[0].endedAt !== null, true);
    assert.match(state.childAttempts[0].handoffEvidence, /committed branch state/);
    assert.equal(state.childAttempts[1].child.ref, "session-two");
    assert.ok(state.history.some((entry) => entry.kind === "evidence" && /replacement 1/i.test(entry.message)));

    expectStateError(
        () =>
            update(state, {
                child: { kind: "task_agent", ref: "agent-three", name: "Third worker" },
                replacementReason: "Second child failed.",
                handoffEvidence: "Attempted another handoff.",
            }),
        "replacement_limit",
    );
});

test("stopped supervision is terminal and delayed child results cannot revive it", () => {
    let state = initial();
    state = update(state, {
        status: "stopped",
        criteria: CRITERIA.map((criterion) => ({
            id: criterion.id,
            status: "passed",
            evidence: `${criterion.id} proof recorded before stop`,
        })),
    });
    expectStateError(() => update(state, { status: "running" }), "terminal_state");
    expectStateError(() => append(state, { message: "delayed child result" }), "terminal_state");
    expectStateError(() => block(state, { reason: "late blocker" }), "terminal_state");
    expectStateError(() => complete(state, { evidence: "late completion" }), "terminal_state");
});

test("completion requires all evidence and terminal state cannot regress", () => {
    let state = initial();
    state = update(state, {
        criteria: CRITERIA.map((criterion) => ({
            id: criterion.id,
            status: "passed",
            evidence: `${criterion.id} proof`,
        })),
    });
    state = complete(
        state,
        { evidence: "Parent inspected the final diff and reran the authoritative suite." },
        { now: "2026-07-15T12:05:00.000Z" },
    );
    assert.equal(state.status, "completed");
    assert.equal(state.progress.percent, 100);
    expectStateError(() => update(state, { status: "running" }), "terminal_state");
    expectStateError(() => complete(state, { evidence: "again" }), "already_completed");
    expectStateError(() => update(state, { criteria: [{ id: "behavior", status: "pending" }] }), "terminal_state");
    expectStateError(() => append(state, { message: "late event" }), "terminal_state");
});

test("stored state is rehydrated, validated, and never reset on corrupt JSON", async (t) => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-state-"));
    t.after(() => fs.rm(dir, { recursive: true, force: true }));

    const first = await openGoalState({
        dir,
        goalId: "rehydrate-goal",
        input: {
            objective: "Original objective",
            criteria: CRITERIA,
            maxRounds: 3,
        },
        now: NOW,
    });
    assert.equal(first.created, true);
    const updated = update(first.state, {
        criteria: [{ id: "behavior", status: "passed", evidence: "proof" }],
    });
    await writeStateFileAtomic(first.statePath, updated);

    const reopened = await openGoalState({
        dir,
        goalId: "rehydrate-goal",
        input: {
            objective: "Attempted reset",
            criteria: CRITERIA,
        },
    });
    assert.equal(reopened.created, false);
    assert.equal(reopened.state.objective, "Original objective");
    assert.equal(reopened.state.progress.passedCount, 1);

    await fs.writeFile(first.statePath, "{broken", "utf8");
    await assert.rejects(
        openGoalState({
            dir,
            goalId: "rehydrate-goal",
            input: { objective: "Must not replace corrupt state", criteria: CRITERIA },
        }),
        (error) => error instanceof SuperGoalStateError && error.code === "state_corrupt",
    );
});

test("serialized concurrent updates preserve both events", async (t) => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-lock-"));
    t.after(() => fs.rm(dir, { recursive: true, force: true }));
    const statePath = resolveStatePath(dir, "concurrent-goal");
    const state = initial({ goalId: "concurrent-goal" });
    await writeStateFileAtomic(statePath, state);

    await Promise.all([
        updateGoalState(statePath, "concurrent-goal", (current) =>
            append(current, { message: "first event" }),
        ),
        updateGoalState(statePath, "concurrent-goal", (current) =>
            append(current, { message: "second event" }),
        ),
    ]);

    const final = await readStateFile(statePath);
    assert.equal(final.revision, state.revision + 2);
    assert.ok(final.history.some((entry) => entry.message === "first event"));
    assert.ok(final.history.some((entry) => entry.message === "second event"));
    expectStateError(
        () => applyAppendEvent(final, { expectedRevision: final.revision - 1, message: "stale" }),
        "stale_revision",
    );
});

test("history remains bounded while current state survives", () => {
    let state = initial();
    for (let index = 0; index < MAX_HISTORY_ENTRIES + 25; index += 1) {
        state = append(state, { message: `event ${index}` });
    }
    assert.equal(state.history.length, MAX_HISTORY_ENTRIES);
    assert.equal(state.objective, "Ship the supervised objective");
    assert.equal(state.history.at(-1).message, `event ${MAX_HISTORY_ENTRIES + 24}`);
});

test("the exact on-disk serialization remains within the state-size cap", async (t) => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-size-"));
    t.after(() => fs.rm(dir, { recursive: true, force: true }));
    let state = initial({ goalId: "sized-goal" });
    for (let index = 0; index < MAX_HISTORY_ENTRIES + 10; index += 1) {
        state = append(state, { message: `${index}:${"x".repeat(2500)}` });
    }
    const statePath = resolveStatePath(dir, "sized-goal");
    await writeStateFileAtomic(statePath, state);
    assert.ok((await fs.stat(statePath)).size <= MAX_STATE_BYTES);
    assert.equal((await readStateFile(statePath)).goalId, "sized-goal");
});

test("steering events consume a monotonic server-managed round budget", () => {
    let state = initial({ maxRounds: 2 });
    expectStateError(() => update(state, { round: 1 }), "invalid_field");
    state = append(state, { kind: "steer", message: "First steering instruction" });
    assert.equal(state.round, 1);
    state = append(state, { kind: "steer", message: "Second steering instruction" });
    assert.equal(state.round, 2);
    expectStateError(
        () => append(state, { kind: "steer", message: "Unbounded third steering instruction" }),
        "steering_limit",
    );
    state = append(state, { kind: "evidence", message: "Evidence remains recordable at the bound." });
    assert.equal(state.round, 2);
});

test("state directory is session-scoped and durable keys never use instance ids", () => {
    assert.equal(
        resolveStateDir({ workspacePath: "/workspace/session", sessionId: "ignored" }),
        path.join("/workspace/session", "files", "super-goal"),
    );
    assert.equal(
        resolveStateDir({ pluginDataPath: "/plugin-data", sessionId: "session-a" }),
        path.join("/plugin-data", "super-goal", "session-a"),
    );
    expectStateError(
        () => resolveStateDir({ workspacePath: undefined, sessionId: "../bad", env: { COPILOT_HOME: "/copilot" } }),
        "invalid_session_id",
    );
    for (const sessionId of [".", "..", "...", "-leading"]) {
        expectStateError(
            () => resolveStateDir({ workspacePath: undefined, sessionId, env: { COPILOT_HOME: "/copilot" } }),
            "invalid_session_id",
        );
    }
    assert.notEqual(
        resolveStateDir({ sessionId: "session-a", env: { COPILOT_HOME: "/copilot" } }),
        resolveStateDir({ sessionId: "session-b", env: { COPILOT_HOME: "/copilot" } }),
    );
    assert.equal(resolveStatePath("/state", "goal-1"), path.join("/state", "goal-1.json"));
});

test("stored-state validation rejects fabricated progress and passed criteria without evidence", () => {
    const state = initial();
    const fabricated = structuredClone(state);
    fabricated.progress = { passedCount: 3, totalCount: 3, percent: 100 };
    expectStateError(() => validateStoredState(fabricated, "sg-test"), "state_corrupt");
    const unknownProgress = structuredClone(state);
    unknownProgress.progress.extra = "tampered";
    expectStateError(() => validateStoredState(unknownProgress, "sg-test"), "state_corrupt");

    const missingEvidence = structuredClone(state);
    missingEvidence.criteria[0].status = "passed";
    expectStateError(() => validateStoredState(missingEvidence, "sg-test"), "state_corrupt");
});

test("a criterion needs fresh evidence every time it transitions back to passed", () => {
    let state = initial();
    state = update(state, {
        criteria: [{ id: "behavior", status: "passed", evidence: "old proof" }],
    });
    state = update(state, {
        criteria: [{ id: "behavior", status: "pending" }],
    });
    assert.equal(state.criteria[0].evidence, null);
    expectStateError(
        () => update(state, { criteria: [{ id: "behavior", status: "passed" }] }),
        "missing_evidence",
    );
    state = update(state, {
        criteria: [{ id: "behavior", status: "passed", evidence: "fresh proof" }],
    });
    assert.equal(state.criteria[0].evidence, "fresh proof");
});

test("criterion evidence changes remain in immutable event history", () => {
    let state = initial();
    state = update(state, {
        criteria: [{ id: "behavior", status: "active", evidence: "Initial diagnostic evidence" }],
    });
    state = update(state, {
        criteria: [{ id: "behavior", status: "passed", evidence: "Final passing evidence" }],
    });
    const evidenceHistory = state.history.filter(
        (entry) => entry.kind === "evidence" && /Criterion behavior evidence updated/.test(entry.message),
    );
    assert.deepEqual(
        evidenceHistory.map((entry) => entry.evidence),
        ["Initial diagnostic evidence", "Final passing evidence"],
    );
});

test("concurrent first writes for different goals share directory creation safely", async (t) => {
    const trustedRoot = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-first-write-"));
    t.after(() => fs.rm(trustedRoot, { recursive: true, force: true }));
    const dir = path.join(trustedRoot, "files", "super-goal");
    await Promise.all(
        ["first-goal", "second-goal"].map((goalId) =>
            writeStateFileAtomic(resolveStatePath(dir, goalId), initial({ goalId }), { trustedRoot }),
        ),
    );
    for (const goalId of ["first-goal", "second-goal"]) {
        const stored = await readStateFile(resolveStatePath(dir, goalId), { trustedRoot });
        assert.equal(stored.goalId, goalId);
    }
});

test("oversized, malformed, and symlinked durable state fails visibly", async (t) => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-tamper-"));
    t.after(() => fs.rm(dir, { recursive: true, force: true }));
    const statePath = resolveStatePath(dir, "tamper-goal");
    const state = initial({ goalId: "tamper-goal" });
    await writeStateFileAtomic(statePath, state);

    const oversized = structuredClone(state);
    oversized.objective = "x".repeat(2001);
    await fs.writeFile(statePath, `${JSON.stringify(oversized)}\n`, "utf8");
    await assert.rejects(readStateFile(statePath).then((value) => validateStoredState(value, "tamper-goal")), {
        code: "state_corrupt",
    });

    await fs.writeFile(statePath, "x".repeat(262_145), "utf8");
    await assert.rejects(readStateFile(statePath), { code: "state_corrupt" });

    const target = path.join(dir, "other.json");
    await fs.writeFile(target, `${JSON.stringify(state)}\n`, "utf8");
    await fs.rm(statePath, { force: true });
    try {
        await fs.symlink(target, statePath);
    } catch (error) {
        if (error?.code === "EPERM" || error?.code === "EACCES") {
            t.diagnostic("file symlink creation is unavailable on this Windows host");
            return;
        }
        throw error;
    }
    await assert.rejects(readStateFile(statePath), { code: "state_corrupt" });
});

test("a symlinked state-directory ancestor cannot redirect session storage", async (t) => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-ancestor-"));
    t.after(() => fs.rm(root, { recursive: true, force: true }));
    const workspace = path.join(root, "workspace");
    const redirected = path.join(root, "redirected");
    await fs.mkdir(workspace);
    await fs.mkdir(redirected);
    try {
        await fs.symlink(redirected, path.join(workspace, "files"), "dir");
    } catch (error) {
        if (error?.code === "EPERM" || error?.code === "EACCES") {
            t.diagnostic("directory symlink creation is unavailable on this Windows host");
            return;
        }
        throw error;
    }
    const dir = path.join(workspace, "files", "super-goal");
    const statePath = resolveStatePath(dir, "redirect-goal");
    const state = initial({ goalId: "redirect-goal" });
    await assert.rejects(writeStateFileAtomic(statePath, state, { trustedRoot: workspace }), {
        code: "state_corrupt",
    });
});

test("a symlinked trusted root is rejected", async (t) => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-root-link-"));
    t.after(() => fs.rm(root, { recursive: true, force: true }));
    const actual = path.join(root, "actual");
    const linked = path.join(root, "linked");
    await fs.mkdir(actual);
    try {
        await fs.symlink(actual, linked, "dir");
    } catch (error) {
        if (error?.code === "EPERM" || error?.code === "EACCES") {
            t.diagnostic("directory symlink creation is unavailable on this Windows host");
            return;
        }
        throw error;
    }
    const dir = path.join(linked, "files", "super-goal");
    const statePath = resolveStatePath(dir, "linked-root-goal");
    await assert.rejects(
        writeStateFileAtomic(statePath, initial({ goalId: "linked-root-goal" }), { trustedRoot: linked }),
        { code: "state_corrupt" },
    );
});

test("state-file disappearance after lstat is corruption, not a fresh-goal reset", async (t) => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "super-goal-disappear-"));
    t.after(() => fs.rm(dir, { recursive: true, force: true }));
    const statePath = resolveStatePath(dir, "disappear-goal");
    await writeStateFileAtomic(statePath, initial({ goalId: "disappear-goal" }));

    const originalOpen = fs.open;
    fs.open = async (...args) => {
        await fs.rm(statePath, { force: true });
        return originalOpen(...args);
    };
    try {
        await assert.rejects(readStateFile(statePath), { code: "state_corrupt" });
    } finally {
        fs.open = originalOpen;
    }
});

test("event broadcaster fans out and isolates a failing sink", () => {
    const broadcaster = new EventBroadcaster();
    const received = [];
    const unsubscribeA = broadcaster.subscribe("goal", (event) => received.push(["a", event]));
    broadcaster.subscribe("goal", () => {
        throw new Error("sink failed");
    });
    const unsubscribeB = broadcaster.subscribe("goal", (event) => received.push(["b", event]));

    assert.equal(broadcaster.publish("goal", { revision: 2 }), 3);
    assert.deepEqual(received, [
        ["a", { revision: 2 }],
        ["b", { revision: 2 }],
    ]);
    unsubscribeA();
    unsubscribeB();
    assert.equal(broadcaster.subscriberCount("goal"), 1);
});

test("renderer escapes identifiers and keeps goal content out of executable HTML", () => {
    assert.equal(escapeHtml(`<script x="1">'&`), "&lt;script x=&quot;1&quot;&gt;&#39;&amp;");
    const html = renderShell({
        instanceId: `panel"><script>alert(1)</script>`,
        goalId: `goal</title><script>alert(2)</script>`,
        nonce: `nonce"><script>alert(3)</script>`,
    });
    assert.doesNotMatch(html, /<script>alert\([123]\)<\/script>/);
    assert.match(html, /goal&lt;\/title&gt;&lt;script&gt;alert\(2\)&lt;\/script&gt;/);
    assert.match(html, /var\(--background-color-default/);
    assert.match(html, /textContent/);
    assert.doesNotMatch(html, /innerHTML/);
    assert.match(html, /prefers-reduced-motion/);
    assert.match(html, /id="handoff-segments"/);
    assert.match(html, /state_error/);
});
