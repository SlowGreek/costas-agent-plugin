// Pure, dependency-free state engine for the super-goal-progress canvas.
//
// This module owns every durable-state concern so it can be unit tested with
// `node:test` without an SDK connection: id/path validation, size caps, the
// atomic on-disk format, per-goal write serialization, and the reducers each
// canvas action calls into. `extension.mjs` is thin SDK/HTTP wiring around
// these functions; it must stay the only place that talks to
// `@github/copilot-sdk`.

import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

export const SCHEMA_VERSION = 1;

// A goalId is used verbatim as a filename stem, so the pattern excludes path
// separators and forbids a leading `.` (which also rules out `.`/`..` and any
// dotfile-style id outright). Mirrors the runtime's own canvas instanceId
// pattern, scaled to a shorter, dashboard-friendly length.
export const GOAL_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export const MIN_CRITERIA = 3;
export const MAX_CRITERIA = 8;

export const DEFAULT_MAX_ROUNDS = 12;
export const HARD_MAX_ROUNDS = 50;
export const MAX_REPLACEMENTS = 1;

export const MAX_OBJECTIVE_CHARS = 2000;
export const MAX_LABEL_CHARS = 200;
export const MAX_STEP_CHARS = 500;
export const MAX_MESSAGE_CHARS = 4000;
export const MAX_EVIDENCE_CHARS = 4000;
export const MAX_REASON_CHARS = 2000;
export const MAX_NAME_CHARS = 200;
export const MAX_REF_CHARS = 200;
export const MAX_ID_CHARS = 64;

export const MAX_HISTORY_ENTRIES = 100;
// Soft cap on the serialized state file size. When exceeded, oldest history
// entries are trimmed first (never the criteria/objective/status fields) so
// the dashboard degrades by losing old narrative, not current structure.
export const MAX_STATE_BYTES = 262_144; // 256 KiB

export const CRITERION_STATUSES = Object.freeze(["pending", "active", "passed", "failed"]);
export const GOAL_STATUSES = Object.freeze([
    "pending",
    "running",
    "paused",
    "blocked",
    "stopped",
    "completed",
]);
export const CHILD_KINDS = Object.freeze(["project_session", "task_agent", "none"]);
export const EVENT_KINDS = Object.freeze(["system", "note", "steer", "evidence"]);

const TRUNCATION_MARKER = "…[truncated]";

/** Raised for structural/business-rule rejections. Never wraps secrets. */
export class SuperGoalStateError extends Error {
    constructor(code, message) {
        super(message);
        this.name = "SuperGoalStateError";
        this.code = code;
    }
}

function invalid(code, message) {
    throw new SuperGoalStateError(code, message);
}

export function isValidGoalId(goalId) {
    return typeof goalId === "string" && GOAL_ID_PATTERN.test(goalId);
}

export function assertValidGoalId(goalId) {
    if (!isValidGoalId(goalId)) {
        invalid(
            "invalid_goal_id",
            "goalId must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ (no path separators or leading dot)",
        );
    }
    return goalId;
}

function nowIso() {
    return new Date().toISOString();
}

/** Truncates freeform text with a visible marker rather than silently dropping content. */
export function sanitizeText(value, maxChars, { required = false, label = "value" } = {}) {
    if (value === undefined || value === null) {
        if (required) invalid("missing_field", `${label} is required`);
        return required ? "" : undefined;
    }
    if (typeof value !== "string") invalid("invalid_field", `${label} must be a string`);
    const trimmed = value.trim();
    if (required && trimmed.length === 0) invalid("missing_field", `${label} must not be empty`);
    if (trimmed.length <= maxChars) return trimmed;
    const keep = Math.max(0, maxChars - TRUNCATION_MARKER.length);
    return `${trimmed.slice(0, keep)}${TRUNCATION_MARKER}`;
}

function sanitizeId(value, label) {
    if (typeof value !== "string" || value.trim().length === 0) {
        invalid("invalid_field", `${label} must be a non-empty string`);
    }
    const trimmed = value.trim();
    if (trimmed.length > MAX_ID_CHARS) {
        invalid("invalid_field", `${label} must be at most ${MAX_ID_CHARS} characters`);
    }
    return trimmed;
}

function sanitizeChild(child) {
    if (child === undefined || child === null) return { kind: "none" };
    if (typeof child !== "object" || Array.isArray(child)) {
        invalid("invalid_field", "child must be an object");
    }
    const kind = child.kind === undefined ? "none" : child.kind;
    if (!CHILD_KINDS.includes(kind)) {
        invalid("invalid_field", `child.kind must be one of ${CHILD_KINDS.join(", ")}`);
    }
    const result = { kind };
    if (child.ref !== undefined) result.ref = sanitizeText(child.ref, MAX_REF_CHARS, { label: "child.ref" });
    if (child.name !== undefined) result.name = sanitizeText(child.name, MAX_NAME_CHARS, { label: "child.name" });
    if (kind !== "none" && !result.ref) {
        invalid("invalid_field", "child.ref is required for a delegated child");
    }
    if (kind === "none" && (result.ref || result.name)) {
        invalid("invalid_field", "child metadata must be empty when child.kind is none");
    }
    return result;
}

function childIdentity(child) {
    return `${child.kind}:${child.ref ?? ""}`;
}

function createChildAttempt(child, attempt, now) {
    return {
        attempt,
        child,
        startedAt: now,
        endedAt: null,
        replacementReason: null,
        handoffEvidence: null,
    };
}

function sanitizeMaxRounds(value) {
    if (value === undefined || value === null) return DEFAULT_MAX_ROUNDS;
    if (!Number.isInteger(value) || value < 1 || value > HARD_MAX_ROUNDS) {
        invalid("invalid_field", `maxRounds must be an integer between 1 and ${HARD_MAX_ROUNDS}`);
    }
    return value;
}

function normalizeCriteriaInput(criteria, now = nowIso()) {
    if (!Array.isArray(criteria)) invalid("invalid_criteria", "criteria must be an array");
    if (criteria.length < MIN_CRITERIA || criteria.length > MAX_CRITERIA) {
        invalid(
            "invalid_criteria_count",
            `criteria must contain between ${MIN_CRITERIA} and ${MAX_CRITERIA} items (got ${criteria.length})`,
        );
    }
    const seenIds = new Set();
    const seenLabels = new Set();
    return criteria.map((entry, index) => {
        if (typeof entry !== "object" || entry === null) {
            invalid("invalid_criteria", `criteria[${index}] must be an object`);
        }
        const id = sanitizeId(entry.id, `criteria[${index}].id`);
        const label = sanitizeText(entry.label, MAX_LABEL_CHARS, {
            required: true,
            label: `criteria[${index}].label`,
        });
        const idKey = id.toLowerCase();
        const labelKey = label.toLowerCase();
        if (seenIds.has(idKey)) invalid("duplicate_criteria", `duplicate criteria id: ${id}`);
        if (seenLabels.has(labelKey)) invalid("duplicate_criteria", `duplicate criteria label: ${label}`);
        seenIds.add(idKey);
        seenLabels.add(labelKey);
        return {
            id,
            label,
            status: "pending",
            evidence: null,
            updatedAt: now,
        };
    });
}

function serializeStateForDisk(state) {
    return `${JSON.stringify(state)}\n`;
}

function computeStateBytes(state) {
    return Buffer.byteLength(serializeStateForDisk(state), "utf8");
}

function assertStoredText(value, maxChars, label, { nullable = false, required = false } = {}) {
    if (value === null && nullable) return;
    if (typeof value !== "string") invalid("state_corrupt", `durable Super Goal state has an invalid ${label}`);
    if ((required && value.trim().length === 0) || value.length > maxChars) {
        invalid("state_corrupt", `durable Super Goal state has an invalid ${label}`);
    }
}

function assertStoredKeys(value, allowed, label) {
    for (const key of Object.keys(value)) {
        if (!allowed.has(key)) invalid("state_corrupt", `durable Super Goal state has an unknown ${label} field`);
    }
}

function validateStoredChild(child, label = "child") {
    if (typeof child !== "object" || child === null || Array.isArray(child)) {
        invalid("state_corrupt", `durable Super Goal state has invalid ${label} metadata`);
    }
    assertStoredKeys(child, new Set(["kind", "ref", "name"]), label);
    if (!CHILD_KINDS.includes(child.kind)) {
        invalid("state_corrupt", `durable Super Goal state has an invalid ${label} kind`);
    }
    if (child.ref !== undefined) assertStoredText(child.ref, MAX_REF_CHARS, `${label} reference`);
    if (child.name !== undefined) assertStoredText(child.name, MAX_NAME_CHARS, `${label} name`);
    if (child.kind !== "none" && (typeof child.ref !== "string" || child.ref.trim().length === 0)) {
        invalid("state_corrupt", `durable Super Goal state has no ${label} reference`);
    }
    if (child.kind === "none" && (child.ref !== undefined || child.name !== undefined)) {
        invalid("state_corrupt", `durable Super Goal state has unexpected ${label} identity fields`);
    }
}

/** Trims oldest history entries until both the count and byte-size caps are satisfied. */
function trimHistory(state) {
    while (state.history.length > MAX_HISTORY_ENTRIES) {
        state.history.shift();
    }
    while (state.history.length > 1 && computeStateBytes(state) > MAX_STATE_BYTES) {
        state.history.shift();
    }
    return state;
}

function pushHistory(state, entry) {
    state.historySeq = (state.historySeq ?? state.history.length) + 1;
    state.history.push({ seq: state.historySeq, ...entry });
    trimHistory(state);
}

/** Progress is derived exclusively from criterion status — never time, tokens, messages, or confidence. */
export function computeProgress(criteria) {
    const totalCount = criteria.length;
    const passedCount = criteria.filter((c) => c.status === "passed").length;
    const percent = totalCount === 0 ? 0 : Math.round((passedCount / totalCount) * 100);
    return { passedCount, totalCount, percent };
}

/** Rejects malformed or tampered durable state instead of silently resetting it. */
export function validateStoredState(state, expectedGoalId) {
    if (typeof state !== "object" || state === null || Array.isArray(state)) {
        invalid("state_corrupt", "durable Super Goal state is not an object");
    }
    if (computeStateBytes(state) > MAX_STATE_BYTES) {
        invalid("state_corrupt", "durable Super Goal state exceeds the size limit");
    }
    assertStoredKeys(
        state,
        new Set([
            "schemaVersion",
            "goalId",
            "revision",
            "status",
            "objective",
            "criteria",
            "progress",
            "currentStep",
            "nextStep",
            "round",
            "maxRounds",
            "child",
            "childAttempts",
            "replacementsUsed",
            "blockedReason",
            "completionEvidence",
            "historySeq",
            "history",
            "createdAt",
            "updatedAt",
            "completedAt",
        ]),
        "top-level",
    );
    if (state.schemaVersion !== SCHEMA_VERSION) {
        invalid("state_corrupt", "durable Super Goal state has an unsupported schema version");
    }
    if (!isValidGoalId(state.goalId)) {
        invalid("state_corrupt", "durable Super Goal state has an invalid goal id");
    }
    if (state.goalId !== expectedGoalId) {
        invalid("state_corrupt", "durable Super Goal state does not match the requested goal");
    }
    if (!Number.isInteger(state.revision) || state.revision < 1) {
        invalid("state_corrupt", "durable Super Goal state has an invalid revision");
    }
    if (!GOAL_STATUSES.includes(state.status)) {
        invalid("state_corrupt", "durable Super Goal state has an invalid status");
    }
    assertStoredText(state.objective, MAX_OBJECTIVE_CHARS, "objective", { required: true });
    assertStoredText(state.currentStep, MAX_STEP_CHARS, "current step", { nullable: true });
    assertStoredText(state.nextStep, MAX_STEP_CHARS, "next step", { nullable: true });
    if (!Number.isInteger(state.maxRounds) || state.maxRounds < 1 || state.maxRounds > HARD_MAX_ROUNDS) {
        invalid("state_corrupt", "durable Super Goal state has an invalid steering bound");
    }
    if (!Number.isInteger(state.round) || state.round < 0 || state.round > state.maxRounds) {
        invalid("state_corrupt", "durable Super Goal state has an invalid steering round");
    }
    validateStoredChild(state.child);
    if (
        !Array.isArray(state.childAttempts) ||
        state.childAttempts.length > MAX_REPLACEMENTS + 1 ||
        !Number.isInteger(state.replacementsUsed) ||
        state.replacementsUsed < 0 ||
        state.replacementsUsed > MAX_REPLACEMENTS ||
        state.replacementsUsed !== Math.max(0, state.childAttempts.length - 1)
    ) {
        invalid("state_corrupt", "durable Super Goal state has invalid child-attempt metadata");
    }
    if ((state.child.kind === "none") !== (state.childAttempts.length === 0)) {
        invalid("state_corrupt", "durable Super Goal state has inconsistent child-attempt metadata");
    }
    for (const [index, attempt] of state.childAttempts.entries()) {
        if (typeof attempt !== "object" || attempt === null || Array.isArray(attempt)) {
            invalid("state_corrupt", "durable Super Goal state has an invalid child attempt");
        }
        assertStoredKeys(
            attempt,
            new Set(["attempt", "child", "startedAt", "endedAt", "replacementReason", "handoffEvidence"]),
            "child attempt",
        );
        if (attempt.attempt !== index + 1) {
            invalid("state_corrupt", "durable Super Goal state has an invalid child-attempt sequence");
        }
        validateStoredChild(attempt.child, "attempt child");
        if (attempt.child.kind === "none") {
            invalid("state_corrupt", "durable Super Goal state has an empty child attempt");
        }
        assertStoredText(attempt.startedAt, 64, "child-attempt start timestamp", { required: true });
        assertStoredText(attempt.endedAt, 64, "child-attempt end timestamp", { nullable: true });
        assertStoredText(attempt.replacementReason, MAX_REASON_CHARS, "replacement reason", { nullable: true });
        assertStoredText(attempt.handoffEvidence, MAX_EVIDENCE_CHARS, "replacement handoff", { nullable: true });
        const isLast = index === state.childAttempts.length - 1;
        if (
            (!isLast &&
                (!attempt.endedAt ||
                    !attempt.replacementReason ||
                    !attempt.handoffEvidence)) ||
            (isLast && attempt.endedAt !== null)
        ) {
            invalid("state_corrupt", "durable Super Goal state has an incomplete child handoff");
        }
    }
    if (
        state.childAttempts.length > 0 &&
        childIdentity(state.childAttempts.at(-1).child) !== childIdentity(state.child)
    ) {
        invalid("state_corrupt", "durable Super Goal state current child does not match its latest attempt");
    }
    assertStoredText(state.blockedReason, MAX_REASON_CHARS, "blocked reason", { nullable: true });
    assertStoredText(state.completionEvidence, MAX_EVIDENCE_CHARS, "completion evidence", { nullable: true });
    assertStoredText(state.createdAt, 64, "created timestamp", { required: true });
    assertStoredText(state.updatedAt, 64, "updated timestamp", { required: true });
    assertStoredText(state.completedAt, 64, "completion timestamp", { nullable: true });
    if (!Array.isArray(state.criteria) || state.criteria.length < MIN_CRITERIA || state.criteria.length > MAX_CRITERIA) {
        invalid("state_corrupt", "durable Super Goal state has an invalid acceptance checklist");
    }
    const seen = new Set();
    for (const criterion of state.criteria) {
        if (typeof criterion !== "object" || criterion === null || Array.isArray(criterion)) {
            invalid("state_corrupt", "durable Super Goal state has an invalid criterion");
        }
        assertStoredKeys(criterion, new Set(["id", "label", "status", "evidence", "updatedAt"]), "criterion");
        if (typeof criterion.id !== "string" || criterion.id.length === 0 || criterion.id.length > MAX_ID_CHARS) {
            invalid("state_corrupt", "durable Super Goal state has an invalid criterion id");
        }
        const id = criterion.id;
        const key = id.toLowerCase();
        if (seen.has(key)) invalid("state_corrupt", "durable Super Goal state has duplicate criterion ids");
        seen.add(key);
        assertStoredText(criterion.label, MAX_LABEL_CHARS, "criterion label", { required: true });
        if (!CRITERION_STATUSES.includes(criterion.status)) {
            invalid("state_corrupt", "durable Super Goal state has an invalid criterion status");
        }
        assertStoredText(criterion.evidence, MAX_EVIDENCE_CHARS, "criterion evidence", { nullable: true });
        assertStoredText(criterion.updatedAt, 64, "criterion timestamp", { required: true });
        if (
            criterion.status === "passed" &&
            (typeof criterion.evidence !== "string" || criterion.evidence.trim().length === 0)
        ) {
            invalid("state_corrupt", "a passed Super Goal criterion is missing evidence");
        }
    }
    if (!Array.isArray(state.history)) {
        invalid("state_corrupt", "durable Super Goal state has an invalid event history");
    }
    if (state.history.length > MAX_HISTORY_ENTRIES || !Number.isInteger(state.historySeq) || state.historySeq < 0) {
        invalid("state_corrupt", "durable Super Goal state has an invalid event history");
    }
    let previousSeq = 0;
    for (const entry of state.history) {
        if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
            invalid("state_corrupt", "durable Super Goal state has an invalid event");
        }
        assertStoredKeys(entry, new Set(["seq", "at", "kind", "message", "evidence"]), "event");
        if (!Number.isInteger(entry.seq) || entry.seq <= previousSeq || entry.seq > state.historySeq) {
            invalid("state_corrupt", "durable Super Goal state has an invalid event sequence");
        }
        previousSeq = entry.seq;
        if (!EVENT_KINDS.includes(entry.kind)) {
            invalid("state_corrupt", "durable Super Goal state has an invalid event kind");
        }
        assertStoredText(entry.at, 64, "event timestamp", { required: true });
        assertStoredText(entry.message, MAX_MESSAGE_CHARS, "event message", { required: true });
        assertStoredText(entry.evidence, MAX_EVIDENCE_CHARS, "event evidence", { nullable: true });
    }
    const computedProgress = computeProgress(state.criteria);
    if (
        typeof state.progress !== "object" ||
        state.progress === null ||
        Array.isArray(state.progress) ||
        state.progress.passedCount !== computedProgress.passedCount ||
        state.progress.totalCount !== computedProgress.totalCount ||
        state.progress.percent !== computedProgress.percent
    ) {
        invalid("state_corrupt", "durable Super Goal state has fabricated progress");
    }
    assertStoredKeys(state.progress, new Set(["passedCount", "totalCount", "percent"]), "progress");
    if (state.status === "blocked" && (!state.blockedReason || state.blockedReason.trim().length === 0)) {
        invalid("state_corrupt", "blocked Super Goal state is missing its reason");
    }
    if (
        state.status === "completed" &&
        (computedProgress.percent !== 100 ||
            !state.completionEvidence ||
            !state.completedAt)
    ) {
        invalid("state_corrupt", "completed Super Goal state is missing acceptance evidence");
    }
    return state;
}

function cloneState(state) {
    return JSON.parse(JSON.stringify(state));
}

function checkRevision(state, expectedRevision) {
    if (expectedRevision === undefined || expectedRevision === null) {
        invalid("missing_revision", "expectedRevision is required for every state mutation");
    }
    if (!Number.isInteger(expectedRevision)) {
        invalid("invalid_field", "expectedRevision must be an integer");
    }
    if (expectedRevision !== state.revision) {
        invalid(
            "stale_revision",
            `expectedRevision ${expectedRevision} does not match current revision ${state.revision}`,
        );
    }
}

function assertNotTerminal(state, action) {
    if (state.status === "completed" || state.status === "stopped") {
        invalid(
            "terminal_state",
            `goal is already ${state.status}; ${action} is rejected without an explicit new goal`,
        );
    }
}

/**
 * Builds the initial durable record for a newly opened goal. Never called for
 * a goal that already has durable state — callers must rehydrate instead.
 */
export function createInitialState({ goalId, objective, criteria, child, maxRounds, now = nowIso() }) {
    assertValidGoalId(goalId);
    const cleanObjective = sanitizeText(objective, MAX_OBJECTIVE_CHARS, {
        required: true,
        label: "objective",
    });
    const cleanCriteria = normalizeCriteriaInput(criteria, now);
    const cleanChild = sanitizeChild(child);
    const cleanMaxRounds = sanitizeMaxRounds(maxRounds);
    const childAttempts = cleanChild.kind === "none" ? [] : [createChildAttempt(cleanChild, 1, now)];

    const state = {
        schemaVersion: SCHEMA_VERSION,
        goalId,
        revision: 1,
        status: "pending",
        objective: cleanObjective,
        criteria: cleanCriteria,
        progress: computeProgress(cleanCriteria),
        currentStep: null,
        nextStep: null,
        round: 0,
        maxRounds: cleanMaxRounds,
        child: cleanChild,
        childAttempts,
        replacementsUsed: 0,
        blockedReason: null,
        completionEvidence: null,
        historySeq: 0,
        history: [],
        createdAt: now,
        updatedAt: now,
        completedAt: null,
    };
    pushHistory(state, {
        at: now,
        kind: "system",
        message: "Goal opened for supervision",
        evidence: null,
    });
    return state;
}

function findCriterion(state, id) {
    const criterion = state.criteria.find((c) => c.id === id);
    if (!criterion) invalid("unknown_criterion", `unknown criterion id: ${id}`);
    return criterion;
}

/** Reducer for the `update_progress` action. Returns a new state object. */
export function applyUpdateProgress(state, patch = {}, { now = nowIso() } = {}) {
    if (typeof patch !== "object" || patch === null || Array.isArray(patch)) {
        invalid("invalid_field", "progress update must be an object");
    }
    checkRevision(state, patch.expectedRevision);
    assertNotTerminal(state, "update_progress");
    const nextStatus = patch.status === undefined ? state.status : patch.status;
    if (patch.status !== undefined && !GOAL_STATUSES.includes(patch.status)) {
        invalid("invalid_field", `status must be one of ${GOAL_STATUSES.join(", ")}`);
    }
    if (patch.status === "completed") {
        invalid("completion_rejected", "use the complete action so acceptance evidence cannot be bypassed");
    }
    if (patch.status === "blocked") {
        invalid("invalid_transition", "use the mark_blocked action so the blocking reason is recorded");
    }

    const next = cloneState(state);
    const changes = [];
    let replacementAudit = null;
    const evidenceAudits = [];

    if (patch.currentStep !== undefined) {
        next.currentStep = sanitizeText(patch.currentStep, MAX_STEP_CHARS, { label: "currentStep" }) || null;
        changes.push("current step updated");
    }
    if (patch.nextStep !== undefined) {
        next.nextStep = sanitizeText(patch.nextStep, MAX_STEP_CHARS, { label: "nextStep" }) || null;
        changes.push("next step updated");
    }
    if (patch.round !== undefined) {
        invalid("invalid_field", "round is server-managed and advances only when a steer event is appended");
    }
    if (patch.child === undefined && (patch.replacementReason !== undefined || patch.handoffEvidence !== undefined)) {
        invalid("invalid_field", "replacement metadata requires a child update");
    }
    if (patch.child !== undefined) {
        const cleanChild = sanitizeChild(patch.child);
        const currentIdentity = childIdentity(next.child);
        const newIdentity = childIdentity(cleanChild);
        if (next.child.kind === "none") {
            if (cleanChild.kind !== "none") {
                if (patch.replacementReason !== undefined || patch.handoffEvidence !== undefined) {
                    invalid("invalid_field", "initial child assignment must not include replacement metadata");
                }
                next.child = cleanChild;
                next.childAttempts.push(createChildAttempt(cleanChild, 1, now));
                changes.push("child attempt 1 registered");
            }
        } else if (newIdentity === currentIdentity) {
            next.child = cleanChild;
            next.childAttempts.at(-1).child = cleanChild;
            changes.push("current child metadata updated");
        } else {
            if (cleanChild.kind === "none") {
                invalid("invalid_transition", "a delegated child cannot be cleared; stop the goal instead");
            }
            if (next.replacementsUsed >= MAX_REPLACEMENTS) {
                invalid("replacement_limit", "the single child replacement has already been used");
            }
            const replacementReason = sanitizeText(patch.replacementReason, MAX_REASON_CHARS, {
                required: true,
                label: "replacementReason",
            });
            const handoffEvidence = sanitizeText(patch.handoffEvidence, MAX_EVIDENCE_CHARS, {
                required: true,
                label: "handoffEvidence",
            });
            const previousAttempt = next.childAttempts.at(-1);
            previousAttempt.endedAt = now;
            previousAttempt.replacementReason = replacementReason;
            previousAttempt.handoffEvidence = handoffEvidence;
            next.replacementsUsed += 1;
            next.child = cleanChild;
            next.childAttempts.push(createChildAttempt(cleanChild, next.childAttempts.length + 1, now));
            changes.push(`child replacement ${next.replacementsUsed} registered with durable handoff`);
            replacementAudit = {
                at: now,
                kind: "evidence",
                message: `Child replacement ${next.replacementsUsed}: ${replacementReason}`,
                evidence: handoffEvidence,
            };
        }
        if (
            newIdentity === currentIdentity &&
            (patch.replacementReason !== undefined || patch.handoffEvidence !== undefined)
        ) {
            invalid("invalid_field", "replacement metadata is only valid when the child identity changes");
        }
    }
    if (patch.criteria !== undefined && !Array.isArray(patch.criteria)) {
        invalid("invalid_criteria", "criteria updates must be an array");
    }
    if (Array.isArray(patch.criteria)) {
        if (patch.criteria.length === 0) {
            invalid("invalid_criteria", "criteria updates must include at least one entry");
        }
        for (const update of patch.criteria) {
            if (typeof update !== "object" || update === null || typeof update.id !== "string") {
                invalid("invalid_criteria", "each criteria update needs an id");
            }
            const criterion = findCriterion(next, update.id);
            const previousStatus = criterion.status;
            const previousEvidence = criterion.evidence;
            if (update.status !== undefined) {
                if (!CRITERION_STATUSES.includes(update.status)) {
                    invalid("invalid_field", `criterion status must be one of ${CRITERION_STATUSES.join(", ")}`);
                }
                if (criterion.status !== update.status) {
                    changes.push(`criterion ${criterion.id}: ${criterion.status} → ${update.status}`);
                }
                if (previousStatus === "passed" && update.status !== "passed") {
                    criterion.evidence = null;
                }
                if (previousStatus !== "passed" && update.status === "passed" && update.evidence === undefined) {
                    invalid("missing_evidence", `criterion ${criterion.id} cannot pass without fresh evidence`);
                }
                criterion.status = update.status;
            }
            if (update.evidence !== undefined) {
                criterion.evidence = sanitizeText(update.evidence, MAX_EVIDENCE_CHARS, {
                    label: `criterion ${criterion.id} evidence`,
                }) || null;
            }
            criterion.updatedAt = now;
            if (
                criterion.status === "passed" &&
                (typeof criterion.evidence !== "string" || criterion.evidence.trim().length === 0)
            ) {
                invalid("missing_evidence", `criterion ${criterion.id} cannot pass without evidence`);
            }
            if (criterion.evidence !== previousEvidence) {
                evidenceAudits.push({
                    at: now,
                    kind: "evidence",
                    message:
                        criterion.evidence === null
                            ? `Criterion ${criterion.id} evidence cleared`
                            : `Criterion ${criterion.id} evidence updated`,
                    evidence: criterion.evidence,
                });
            }
        }
    }
    if (patch.status !== undefined && patch.status !== state.status) {
        changes.push(`status: ${state.status} → ${patch.status}`);
        next.status = patch.status;
        if (state.status === "blocked" && patch.status !== "blocked") {
            next.blockedReason = null;
        }
    }

    next.progress = computeProgress(next.criteria);
    next.revision = state.revision + 1;
    next.updatedAt = now;
    if (changes.length > 0) {
        pushHistory(next, { at: now, kind: "system", message: changes.join("; "), evidence: null });
    }
    if (replacementAudit) pushHistory(next, replacementAudit);
    for (const audit of evidenceAudits) pushHistory(next, audit);
    return next;
}

/** Reducer for the `append_event` action — a caller-authored note, always allowed regardless of status. */
export function applyAppendEvent(state, input = {}, { now = nowIso() } = {}) {
    checkRevision(state, input.expectedRevision);
    assertNotTerminal(state, "append_event");
    const message = sanitizeText(input.message, MAX_MESSAGE_CHARS, { required: true, label: "message" });
    const kind = input.kind === undefined ? "note" : input.kind;
    if (!EVENT_KINDS.includes(kind)) {
        invalid("invalid_field", `kind must be one of ${EVENT_KINDS.join(", ")}`);
    }
    const evidence =
        input.evidence === undefined
            ? null
            : sanitizeText(input.evidence, MAX_EVIDENCE_CHARS, { label: "evidence" }) || null;

    const next = cloneState(state);
    if (kind === "steer") {
        if (state.round >= state.maxRounds) {
            invalid("steering_limit", "the Super Goal steering-round budget is exhausted");
        }
        next.round = state.round + 1;
    }
    next.revision = state.revision + 1;
    next.updatedAt = now;
    pushHistory(next, { at: now, kind, message, evidence });
    return next;
}

/** Reducer for `complete` — rejects unless every criterion has passed and evidence is supplied. */
export function applyComplete(state, input = {}, { now = nowIso() } = {}) {
    checkRevision(state, input.expectedRevision);
    if (state.status === "completed") {
        invalid("already_completed", "goal is already marked complete");
    }
    assertNotTerminal(state, "complete");
    const evidence = sanitizeText(input.evidence, MAX_EVIDENCE_CHARS, {
        required: true,
        label: "evidence",
    });
    const unmet = state.criteria.filter((c) => c.status !== "passed").map((c) => c.id);
    if (unmet.length > 0) {
        invalid(
            "completion_rejected",
            `cannot complete: criteria not yet passed: ${unmet.join(", ")}`,
        );
    }

    const next = cloneState(state);
    next.status = "completed";
    next.blockedReason = null;
    next.completionEvidence = evidence;
    next.completedAt = now;
    next.revision = state.revision + 1;
    next.updatedAt = now;
    next.progress = computeProgress(next.criteria);
    pushHistory(next, { at: now, kind: "system", message: "Goal independently verified and completed", evidence });
    return next;
}

/** Reducer for `mark_blocked` — records why the supervisor is waiting on a human/external decision. */
export function applyMarkBlocked(state, input = {}, { now = nowIso() } = {}) {
    checkRevision(state, input.expectedRevision);
    assertNotTerminal(state, "mark_blocked");
    const reason = sanitizeText(input.reason, MAX_REASON_CHARS, { required: true, label: "reason" });
    const evidence =
        input.evidence === undefined
            ? null
            : sanitizeText(input.evidence, MAX_EVIDENCE_CHARS, { label: "evidence" }) || null;

    const next = cloneState(state);
    next.status = "blocked";
    next.blockedReason = reason;
    next.revision = state.revision + 1;
    next.updatedAt = now;
    pushHistory(next, { at: now, kind: "system", message: `Blocked: ${reason}`, evidence });
    return next;
}

/** Shape returned to HTTP/SSE clients and canvas action callers — recomputes progress defensively. */
export function serializeForClient(state) {
    return {
        ...state,
        progress: computeProgress(state.criteria),
    };
}

// ---------------------------------------------------------------------------
// Persistence: path resolution, atomic writes, and per-goal serialization.
// ---------------------------------------------------------------------------

const SESSION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/**
 * Resolves the durable state directory for a goal. The extension passes its
 * plugin-data root so a supervised child with ordinary workspace access cannot
 * race or replace the dashboard ledger. Workspace and COPILOT_HOME locations
 * remain explicit fallbacks for pure tests and compatible non-extension hosts.
 */
export function resolveStateDir({
    pluginDataPath,
    workspacePath,
    sessionId,
    env = process.env,
    home = os.homedir(),
} = {}) {
    return resolveStateLocation({ pluginDataPath, workspacePath, sessionId, env, home }).dir;
}

export function resolveStateLocation({
    pluginDataPath,
    workspacePath,
    sessionId,
    env = process.env,
    home = os.homedir(),
} = {}) {
    if (pluginDataPath) {
        if (!SESSION_ID_PATTERN.test(sessionId ?? "")) {
            invalid("invalid_session_id", "a validated session id is required for plugin-data state");
        }
        const trustedRoot = path.resolve(pluginDataPath, "super-goal", sessionId);
        return { trustedRoot, dir: trustedRoot };
    }
    if (workspacePath) {
        const trustedRoot = path.resolve(workspacePath);
        return {
            trustedRoot,
            dir: path.join(trustedRoot, "files", "super-goal"),
        };
    }
    const copilotHome = env.COPILOT_HOME?.trim()
        ? path.resolve(env.COPILOT_HOME.trim())
        : path.join(home, ".copilot");
    if (!SESSION_ID_PATTERN.test(sessionId ?? "")) {
        invalid("invalid_session_id", "a validated session id is required when no session workspace is available");
    }
    return {
        trustedRoot: copilotHome,
        dir: path.join(copilotHome, "session-state", sessionId, "files", "super-goal"),
    };
}

/** Never key durable data by instanceId — the file name is the goalId alone. */
export function resolveStatePath(dir, goalId) {
    assertValidGoalId(goalId);
    return path.join(dir, `${goalId}.json`);
}

function pathEqual(left, right) {
    return process.platform === "win32"
        ? path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase()
        : path.resolve(left) === path.resolve(right);
}

async function assertStateDirectory(trustedRoot, targetDir, { create = false } = {}) {
    const root = path.resolve(trustedRoot);
    const target = path.resolve(targetDir);
    const relative = path.relative(root, target);
    if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
        invalid("state_corrupt", "the Super Goal state directory escapes its trusted session root");
    }
    if (create) await fs.mkdir(root, { recursive: true, mode: 0o700 });
    const rootMetadata = await fs.lstat(root);
    if (!rootMetadata.isDirectory() || rootMetadata.isSymbolicLink()) {
        invalid("state_corrupt", "the trusted Super Goal session root must not be a symlink");
    }
    const rootReal = await fs.realpath(root);
    let logical = root;
    let expectedReal = rootReal;
    for (const component of relative.split(path.sep).filter(Boolean)) {
        logical = path.join(logical, component);
        expectedReal = path.join(expectedReal, component);
        let metadata;
        try {
            metadata = await fs.lstat(logical);
        } catch (error) {
            if (!create || !error || error.code !== "ENOENT") throw error;
            try {
                await fs.mkdir(logical);
            } catch (mkdirError) {
                if (!mkdirError || mkdirError.code !== "EEXIST") throw mkdirError;
            }
            metadata = await fs.lstat(logical);
        }
        if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
            invalid("state_corrupt", "the Super Goal state path contains a symlink or non-directory ancestor");
        }
    }
    const actualReal = await fs.realpath(target);
    if (!pathEqual(actualReal, expectedReal)) {
        invalid("state_corrupt", "the Super Goal state path resolves outside its trusted session root");
    }
}

export async function readStateFile(statePath, { trustedRoot = path.dirname(statePath) } = {}) {
    let handle;
    let observedFile = false;
    try {
        await assertStateDirectory(trustedRoot, path.dirname(statePath));
        let metadata;
        try {
            metadata = await fs.lstat(statePath);
        } catch (error) {
            if (!error || error.code !== "ENOENT") throw error;
            try {
                await assertStateDirectory(trustedRoot, path.dirname(statePath));
            } catch (parentError) {
                if (parentError?.code === "ENOENT") {
                    invalid("state_corrupt", "the Super Goal state directory disappeared during a read");
                }
                throw parentError;
            }
            return null;
        }
        observedFile = true;
        if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > MAX_STATE_BYTES) {
            invalid("state_corrupt", "the Super Goal state file is not a bounded regular file");
        }
        handle = await fs.open(statePath, "r");
        const opened = await handle.stat();
        if (opened.dev !== metadata.dev || opened.ino !== metadata.ino) {
            invalid("state_corrupt", "the Super Goal state file changed while it was being opened");
        }
        const buffer = Buffer.alloc(MAX_STATE_BYTES + 1);
        const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
        if (bytesRead > MAX_STATE_BYTES) {
            invalid("state_corrupt", "the Super Goal state file exceeds the size limit");
        }
        const raw = buffer.subarray(0, bytesRead).toString("utf8");
        const parsed = JSON.parse(raw);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
            invalid("state_corrupt", "durable Super Goal state is not an object");
        }
        return parsed;
    } catch (error) {
        if (error && error.code === "ENOENT") {
            if (observedFile) {
                invalid("state_corrupt", "the Super Goal state file disappeared during a read");
            }
            return null;
        }
        if (error instanceof SyntaxError) {
            invalid("state_corrupt", "durable Super Goal state contains invalid JSON");
        }
        throw error;
    } finally {
        await handle?.close().catch(() => {});
    }
}

/** Atomic same-directory write: stage, then rename, so readers never see a partial file. */
export async function writeStateFileAtomic(statePath, state, { trustedRoot = path.dirname(statePath) } = {}) {
    await assertStateDirectory(trustedRoot, path.dirname(statePath), { create: true });
    try {
        const destination = await fs.lstat(statePath);
        if (destination.isSymbolicLink() || !destination.isFile()) {
            invalid("state_corrupt", "the Super Goal state destination must be a regular file");
        }
    } catch (error) {
        if (!error || error.code !== "ENOENT") throw error;
    }
    validateStoredState(state, state.goalId);
    const staging = path.join(
        path.dirname(statePath),
        `.${path.basename(statePath)}.${process.pid}.${crypto.randomBytes(4).toString("hex")}.tmp`,
    );
    try {
        await fs.writeFile(staging, serializeStateForDisk(state), { encoding: "utf8", mode: 0o600 });
        await fs.rename(staging, statePath);
    } finally {
        await fs.rm(staging, { force: true }).catch(() => {});
    }
}

/**
 * Opens (creating if absent) the durable record for a goal. Reopening the
 * same or a different instance for the same goalId always rehydrates the
 * existing file rather than resetting it — the supplied `input` is only used
 * the first time a goalId is seen.
 */
export async function openGoalState({ dir, trustedRoot = dir, goalId, input, now = nowIso() }) {
    assertValidGoalId(goalId);
    const statePath = resolveStatePath(dir, goalId);
    const existing = await readStateFile(statePath, { trustedRoot });
    if (existing) {
        return { state: validateStoredState(existing, goalId), statePath, created: false };
    }
    const state = createInitialState({ ...input, goalId, now });
    await writeStateFileAtomic(statePath, state, { trustedRoot });
    return { state, statePath, created: true };
}

// A single Node process backs the whole extension, so an in-memory per-goal
// promise chain is sufficient to serialize concurrent updates — no cross
// process file locking is needed (unlike goalctl.py, which must coordinate
// across independent CLI invocations).
const goalLocks = new Map();

/** Runs `fn` after any prior queued operation for this goalId settles, guaranteeing no lost writes. */
export function withGoalLock(goalId, fn) {
    const previous = goalLocks.get(goalId) ?? Promise.resolve();
    const result = previous.catch(() => {}).then(fn);
    const settled = result.catch(() => {});
    goalLocks.set(goalId, settled);
    settled.then(() => {
        if (goalLocks.get(goalId) === settled) goalLocks.delete(goalId);
    });
    return result;
}

/** Convenience: read-modify-write a goal's state under its lock, returning the new state. */
export async function updateGoalState(
    statePath,
    goalId,
    mutate,
    { trustedRoot = path.dirname(statePath) } = {},
) {
    return withGoalLock(goalId, async () => {
        const current = await readStateFile(statePath, { trustedRoot });
        if (!current) invalid("state_missing", `no durable state found for goal: ${goalId}`);
        validateStoredState(current, goalId);
        const next = await mutate(current);
        validateStoredState(next, goalId);
        await writeStateFileAtomic(statePath, next, { trustedRoot });
        return next;
    });
}

// ---------------------------------------------------------------------------
// SSE / broadcast fan-out.
// ---------------------------------------------------------------------------

/**
 * Fans a published event out to every subscribed sink for a goalId. Kept
 * independent of any real HTTP response object so it is directly unit
 * testable; `extension.mjs` supplies SSE-writer sinks.
 */
export class EventBroadcaster {
    constructor() {
        this.subscribers = new Map();
    }

    subscribe(goalId, sink) {
        let set = this.subscribers.get(goalId);
        if (!set) {
            set = new Set();
            this.subscribers.set(goalId, set);
        }
        set.add(sink);
        return () => {
            set.delete(sink);
            if (set.size === 0) this.subscribers.delete(goalId);
        };
    }

    publish(goalId, event) {
        const set = this.subscribers.get(goalId);
        if (!set) return 0;
        for (const sink of set) {
            try {
                sink(event);
            } catch {
                // A misbehaving sink must never break delivery to the rest.
            }
        }
        return set.size;
    }

    subscriberCount(goalId) {
        return this.subscribers.get(goalId)?.size ?? 0;
    }
}
