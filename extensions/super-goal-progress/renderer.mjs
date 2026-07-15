// Pure HTML rendering for the super-goal-progress canvas. No SDK or network
// imports here so it can be unit tested directly.
//
// Security posture: the returned shell embeds no dynamic goal text (no
// objective/criteria/event/evidence strings) server-side. The only
// interpolated values are the caller-supplied `instanceId`/`goalId` (both are
// validated elsewhere against a narrow pattern before reaching this module,
// but this file still escapes them defensively) and a per-response CSP
// `nonce`. All state-derived content is populated client-side by the static
// script below via `fetch("/state.json")` / `EventSource("/events")`, using
// `textContent` and `dataset`/attribute assignment — never `innerHTML` — so
// no goal-supplied text can ever be interpreted as markup or script.

const HTML_ESCAPES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
};

/** Escapes the five HTML-significant characters. Safe for text and attribute contexts. */
export function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => HTML_ESCAPES[ch]);
}

// The host mirrors documented semantic canvas theme tokens into this isolated
// document. Namespaced tokens below consume those values first and retain
// deliberate light/dark fallbacks for hosts that predate the canvas theme
// contract.
const STYLE = `
:root{
  color-scheme:light dark;
  --sg-bg:var(--background-color-default,light-dark(#f6f8fa,#0d1117));
  --sg-surface:light-dark(#ffffff,#161b22);
  --sg-surface-muted:light-dark(#f0f2f5,#1c2129);
  --sg-fg:var(--text-color-default,light-dark(#1f2328,#e6edf3));
  --sg-muted:var(--text-color-muted,light-dark(#57606a,#8b949e));
  --sg-border:var(--border-color-default,light-dark(#d0d7de,#30363d));
  --sg-accent:var(--color-focus-outline,light-dark(#0969da,#4493f8));
  --sg-success:var(--true-color-green,light-dark(#1a7f37,#3fb950));
  --sg-warning:var(--true-color-yellow,light-dark(#9a6700,#d29922));
  --sg-danger:var(--true-color-red,light-dark(#cf222e,#f85149));
}
@supports not (color:light-dark(#000,#fff)){
  :root{--sg-bg:#f6f8fa;--sg-surface:#fff;--sg-surface-muted:#f0f2f5;--sg-fg:#1f2328;--sg-muted:#57606a;--sg-border:#d0d7de;--sg-accent:#0969da;--sg-success:#1a7f37;--sg-warning:#9a6700;--sg-danger:#cf222e;}
  @media (prefers-color-scheme:dark){
    :root{--sg-bg:#0d1117;--sg-surface:#161b22;--sg-surface-muted:#1c2129;--sg-fg:#e6edf3;--sg-muted:#8b949e;--sg-border:#30363d;--sg-accent:#4493f8;--sg-success:#3fb950;--sg-warning:#d29922;--sg-danger:#f85149;}
  }
}
*,*::before,*::after{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{
  background:var(--sg-bg);color:var(--sg-fg);
  font-family:var(--font-sans,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif);
  font-size:var(--text-body-medium,14px);line-height:var(--leading-body-medium,1.5);
}
button{font:inherit;color:inherit;background:none;border:none;cursor:pointer;}
:focus-visible{outline:2px solid var(--sg-accent);outline-offset:2px;}
.container{max-width:920px;margin:0 auto;padding:1rem 1.25rem 3rem;}
.app-header{display:flex;align-items:center;justify-content:space-between;gap:.75rem;flex-wrap:wrap;padding:.75rem 0 1rem;border-bottom:1px solid var(--sg-border);margin-bottom:1.25rem;}
.app-header h1{font-size:var(--text-title-medium,1rem);font-weight:var(--font-weight-semibold,600);margin:0;}
.app-header .goal-id{color:var(--sg-muted);font-weight:400;font-size:.85em;}
.header-meta{display:flex;align-items:center;gap:.6rem;}
.pill{display:inline-flex;align-items:center;gap:.35rem;padding:.2rem .65rem;border-radius:999px;border:1px solid var(--sg-border);background:var(--sg-surface);font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.02em;}
.pill[data-status="running"]{border-color:var(--sg-accent);color:var(--sg-accent);}
.pill[data-status="paused"],.pill[data-status="pending"]{color:var(--sg-muted);}
.pill[data-status="blocked"]{border-color:var(--sg-warning);color:var(--sg-warning);}
.pill[data-status="stopped"]{border-color:var(--sg-danger);color:var(--sg-danger);}
.pill[data-status="completed"]{border-color:var(--sg-success);color:var(--sg-success);}
#connection-indicator{font-size:.7rem;color:var(--sg-muted);}
#connection-indicator[data-status="live"]::before{content:"● ";color:var(--sg-success);}
#connection-indicator[data-status="reconnecting"]::before,#connection-indicator[data-status="connecting"]::before{content:"● ";color:var(--sg-warning);}
#connection-indicator[data-status="error"]::before{content:"● ";color:var(--sg-danger);}

.banner{margin:0 0 1.25rem;padding:.75rem 1rem;border-radius:8px;border:1px solid var(--sg-border);background:var(--sg-surface-muted);}
.banner[data-kind="blocked"]{border-color:var(--sg-warning);}
.banner[data-kind="error"]{border-color:var(--sg-danger);}
.banner[data-kind="completed"]{border-color:var(--sg-success);}

/* Signature element: two-node handoff rail. Segments illuminate only as the
   matching acceptance criterion actually passes — this is a supervision
   ownership indicator, not a generic progress bar. */
.handoff-rail{display:flex;align-items:center;gap:.6rem;margin:0 0 1.5rem;}
.handoff-rail .node{flex:0 0 auto;padding:.45rem .8rem;border-radius:999px;border:1px solid var(--sg-border);background:var(--sg-surface);font-weight:600;font-size:.78rem;white-space:nowrap;}
.handoff-rail .node-parent{border-color:var(--sg-accent);color:var(--sg-accent);}
.handoff-rail .node-child{border-color:var(--sg-muted);color:var(--sg-muted);}
.handoff-rail .segments{flex:1 1 auto;display:flex;gap:4px;min-width:60px;}
.handoff-rail .segment{flex:1 1 0;height:10px;border-radius:5px;background:var(--sg-border);transition:background-color .2s ease;}
.handoff-rail .segment[data-status="passed"]{background:var(--sg-success);}
.handoff-rail .segment[data-status="active"]{background:var(--sg-accent);}
.handoff-rail .segment[data-status="failed"]{background:var(--sg-danger);}
@media (max-width:640px){
  .handoff-rail{flex-direction:column;align-items:stretch;}
  .handoff-rail .segments{order:2;}
}

section{margin-bottom:1.5rem;}
section h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;color:var(--sg-muted);margin:0 0 .5rem;}
.card{background:var(--sg-surface);border:1px solid var(--sg-border);border-radius:8px;padding:.9rem 1rem;}
.progress-summary{font-size:.85rem;color:var(--sg-muted);margin:0 0 .5rem;}
.steer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem;}
.steer-grid .field-label{font-size:.7rem;text-transform:uppercase;color:var(--sg-muted);margin:0 0 .2rem;}
.steer-grid .field-value{margin:0;word-break:break-word;}

ul.criteria,ul.history{list-style:none;margin:0;padding:0;}
ul.criteria li{display:flex;gap:.6rem;align-items:flex-start;padding:.5rem 0;border-bottom:1px solid var(--sg-border);}
ul.criteria li:last-child{border-bottom:none;}
.criterion-status{flex:0 0 auto;width:.8rem;height:.8rem;margin-top:.3rem;border-radius:50%;border:2px solid var(--sg-border);}
li[data-status="passed"] .criterion-status{background:var(--sg-success);border-color:var(--sg-success);}
li[data-status="active"] .criterion-status{background:var(--sg-accent);border-color:var(--sg-accent);}
li[data-status="failed"] .criterion-status{background:var(--sg-danger);border-color:var(--sg-danger);}
.criterion-label{font-weight:500;}
.criterion-evidence{margin:.15rem 0 0;color:var(--sg-muted);font-size:.85rem;}

ul.history li{padding:.6rem 0;border-bottom:1px solid var(--sg-border);}
ul.history li:last-child{border-bottom:none;}
ul.history time{display:block;font-size:.72rem;color:var(--sg-muted);}
ul.history p{margin:.15rem 0 0;}
.history-evidence{color:var(--sg-muted);font-size:.85rem;}

@media (prefers-reduced-motion:reduce){
  *{transition:none!important;animation:none!important;}
}
`;

// Static client script (authored once, never templated with request data).
// Populates the DOM purely via textContent/attribute assignment.
const CLIENT_SCRIPT = `
(function () {
  "use strict";
  function byId(id) { return document.getElementById(id); }
  var statusPill = byId("status-pill");
  var connEl = byId("connection-indicator");
  var objectiveEl = byId("objective-text");
  var currentStepEl = byId("current-step-text");
  var nextStepEl = byId("next-step-text");
  var roundEl = byId("round-text");
  var attemptsEl = byId("attempts-text");
  var childEl = byId("child-text");
  var progressEl = byId("progress-text");
  var railSegments = byId("handoff-segments");
  var criteriaEl = byId("criteria-list");
  var historyEl = byId("history-list");
  var bannerEl = byId("state-banner");
  var mainEl = byId("main-content");

  function setText(el, value) {
    if (!el) return;
    el.textContent = value === undefined || value === null || value === "" ? "\u2014" : String(value);
  }

  function renderBanner(kind, message) {
    if (!bannerEl) return;
    if (!kind) {
      bannerEl.hidden = true;
      bannerEl.removeAttribute("data-kind");
      return;
    }
    bannerEl.hidden = false;
    bannerEl.setAttribute("data-kind", kind);
    bannerEl.textContent = message;
  }

  function renderCriteria(criteria) {
    var list = Array.isArray(criteria) ? criteria : [];
    criteriaEl.textContent = "";
    railSegments.textContent = "";
    list.forEach(function (criterion) {
      var item = document.createElement("li");
      item.setAttribute("data-status", criterion.status || "pending");
      var marker = document.createElement("span");
      marker.className = "criterion-status";
      marker.setAttribute("aria-hidden", "true");
      var body = document.createElement("div");
      var label = document.createElement("div");
      label.className = "criterion-label";
      label.textContent = criterion.label || criterion.id || "";
      body.appendChild(label);
      if (criterion.evidence) {
        var evidence = document.createElement("p");
        evidence.className = "criterion-evidence";
        evidence.textContent = criterion.evidence;
        body.appendChild(evidence);
      }
      item.appendChild(marker);
      item.appendChild(body);
      criteriaEl.appendChild(item);

      var segment = document.createElement("span");
      segment.className = "segment";
      segment.setAttribute("role", "presentation");
      segment.setAttribute("data-status", criterion.status || "pending");
      railSegments.appendChild(segment);
    });
  }

  function renderHistory(history) {
    var entries = Array.isArray(history) ? history.slice().reverse() : [];
    historyEl.textContent = "";
    entries.forEach(function (entry) {
      var item = document.createElement("li");
      item.setAttribute("data-kind", entry.kind || "note");
      var time = document.createElement("time");
      time.textContent = entry.at || "";
      if (entry.at) time.setAttribute("datetime", entry.at);
      var message = document.createElement("p");
      message.textContent = entry.message || "";
      item.appendChild(time);
      item.appendChild(message);
      if (entry.evidence) {
        var evidence = document.createElement("p");
        evidence.className = "history-evidence";
        evidence.textContent = entry.evidence;
        item.appendChild(evidence);
      }
      historyEl.appendChild(item);
    });
  }

  function unwrap(payload) {
    return payload && typeof payload === "object" && payload.state !== undefined ? payload.state : payload;
  }

  function render(rawState) {
    var state = unwrap(rawState);
    if (!state || !state.goalId) {
      mainEl.hidden = true;
      renderBanner("empty", "No progress has been reported for this goal yet.");
      return;
    }
    mainEl.hidden = false;
    document.body.setAttribute("data-status", state.status || "pending");
    setText(statusPill, state.status);
    if (statusPill) statusPill.setAttribute("data-status", state.status || "pending");
    setText(objectiveEl, state.objective);
    setText(currentStepEl, state.currentStep);
    setText(nextStepEl, state.nextStep);
    var roundText = (state.round === undefined || state.round === null ? 0 : state.round) +
      (state.maxRounds ? " / " + state.maxRounds : "");
    setText(roundEl, roundText);
    setText(
      attemptsEl,
      (Array.isArray(state.childAttempts) ? state.childAttempts.length : 0) +
        " / 2 child attempts; " + (state.replacementsUsed || 0) + " replacement used"
    );
    var childLabel = state.child && (state.child.name || state.child.ref);
    setText(childEl, childLabel || "Not yet delegated");
    renderCriteria(state.criteria);
    renderHistory(state.history);
    if (state.progress) {
      setText(
        progressEl,
        state.progress.passedCount + " / " + state.progress.totalCount + " criteria passed (" + state.progress.percent + "%)"
      );
    }

    if (state.status === "blocked") {
      renderBanner("blocked", state.blockedReason || "Blocked, awaiting a decision.");
    } else if (state.status === "completed") {
      renderBanner("completed", state.completionEvidence || "Completed.");
    } else if (state.status === "stopped") {
      renderBanner("stopped", "Supervision was stopped.");
    } else {
      renderBanner("", "");
    }
  }

  function setConnection(status) {
    if (connEl) {
      connEl.textContent = status;
      connEl.setAttribute("data-status", status);
    }
  }

  var eventSource = null;

  function connectEvents() {
    if (eventSource) {
      try { eventSource.close(); } catch (err) { /* ignore */ }
    }
    setConnection("connecting");
    eventSource = new EventSource("/events");
    eventSource.addEventListener("open", function () { setConnection("live"); });
    eventSource.addEventListener("error", function () { setConnection("reconnecting"); });
    eventSource.addEventListener("state", function (event) {
      try {
        render(JSON.parse(event.data));
        setConnection("live");
      } catch (err) {
        /* Malformed event payloads are ignored; the next state.json poll recovers. */
      }
    });
    eventSource.addEventListener("state_error", function () {
      mainEl.hidden = true;
      renderBanner("error", "Durable progress state is invalid or unavailable. Supervision is paused until it is repaired.");
      setConnection("error");
      try { eventSource.close(); } catch (err) { /* ignore */ }
    });
  }

  function loadInitial() {
    renderBanner("loading", "Loading progress…");
    fetch("/state.json", { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("status " + res.status);
        return res.json();
      })
      .then(function (data) {
        render(data);
        connectEvents();
      })
      .catch(function () {
        renderBanner("error", "Could not load progress. Retrying…");
        setTimeout(loadInitial, 3000);
      });
  }

  loadInitial();
})();
`;

/**
 * Renders the static canvas shell. `instanceId`/`goalId` are escaped
 * defensively even though upstream validation already restricts their
 * character set; `nonce` must be a fresh, unguessable value generated by the
 * HTTP layer for this response only.
 */
export function renderShell({ instanceId, goalId, nonce }) {
    const safeInstanceId = escapeHtml(instanceId);
    const safeGoalId = escapeHtml(goalId);
    const safeNonce = escapeHtml(nonce);
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="referrer" content="no-referrer" />
<title>Super Goal Mission Control — ${safeGoalId}</title>
<style nonce="${safeNonce}">${STYLE}</style>
</head>
<body data-instance-id="${safeInstanceId}" data-status="pending">
<noscript>This dashboard needs JavaScript enabled to fetch live goal progress.</noscript>
<div class="container">
  <header class="app-header">
    <h1>Super Goal Mission Control <span class="goal-id">${safeGoalId}</span></h1>
    <div class="header-meta">
      <span class="pill" id="status-pill" data-status="pending" role="status">pending</span>
      <span id="connection-indicator" data-status="connecting" role="status" aria-live="polite">connecting</span>
    </div>
  </header>

  <div id="state-banner" class="banner" role="status" aria-live="polite" hidden></div>

  <div id="main-content" hidden>
    <div class="handoff-rail" role="group" aria-label="Supervision ownership and acceptance progress">
      <span class="node node-parent">Parent · Supervisor</span>
      <span class="segments" id="handoff-segments"></span>
      <span class="node node-child">Child · Worker</span>
    </div>

    <section aria-labelledby="objective-heading">
      <h2 id="objective-heading">Objective</h2>
      <p class="card" id="objective-text"></p>
    </section>

    <section aria-labelledby="criteria-heading">
      <h2 id="criteria-heading">Acceptance criteria</h2>
      <p class="progress-summary" id="progress-text"></p>
      <ul class="criteria card" id="criteria-list"></ul>
    </section>

    <section aria-labelledby="steering-heading">
      <h2 id="steering-heading">Steering</h2>
      <div class="card steer-grid">
        <div>
          <p class="field-label">Current step</p>
          <p class="field-value" id="current-step-text"></p>
        </div>
        <div>
          <p class="field-label">Next step</p>
          <p class="field-value" id="next-step-text"></p>
        </div>
        <div>
          <p class="field-label">Round</p>
          <p class="field-value" id="round-text"></p>
        </div>
        <div>
          <p class="field-label">Child session</p>
          <p class="field-value" id="child-text"></p>
        </div>
        <div>
          <p class="field-label">Attempts</p>
          <p class="field-value" id="attempts-text"></p>
        </div>
      </div>
    </section>

    <section aria-labelledby="history-heading">
      <h2 id="history-heading">Evidence &amp; events</h2>
      <ul class="history card" id="history-list"></ul>
    </section>
  </div>
</div>
<script nonce="${safeNonce}">${CLIENT_SCRIPT}</script>
</body>
</html>
`;
}
