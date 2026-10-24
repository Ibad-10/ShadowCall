import { api, setCsrf, esc, icon, pct, pence, ago, ApiError } from "/static/js/api.js";
import { NAMES, stName, plain, tip, TIPS, explainer, wireExplainer, flowHtml, wireFlow, GLOSSARY, startTour, tourSeen } from "/static/js/guide.js";

const SUBTASKS = ["extract", "policy_check", "form_fill", "summary"];
const TRIGGER = 25; // Mubit's per-task training trigger: the console warns, it never pushes past it
const LANES = {
  teacher: { label: "Big model", color: "var(--frontier)" },
  shadow: { label: "Small, untrained", color: "#5B6573" },
  adapter_raw: { label: "Small, learned from every answer", color: "#6871C4" },
  adapter_verified: { label: "Small, learned from checked answers", color: "var(--small)" },
};
const STATUS = {
  needs_human: ["Needs a person", "b-warn"],
  kept_correction_turn: ["Fixed by correction turn", "b-ok"],
  kept_verified_resample: ["Fixed by re-ask", "b-ok"],
  human_fixed: ["Approved by a person", "b-info"],
  correction_turn_replay_failed: ["Replay failed", "b-bad"],
  kept_unverified_rate_bad: ["Kept unverified", "b-bad"],
};

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const content = $("#content");
const ctx = { me: null, settings: null, ctrl: null, timers: [], stops: [], feedCursor: 0, page: null };

/* ---------- small UI kit ---------- */
function toast(title, body = "", kind = "ok") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === "ok" ? "circle-check" : kind === "bad" ? "circle-x" : "info")}<div><b>${esc(title)}</b>${body ? `<span>${esc(body)}</span>` : ""}</div>`;
  $("[data-toasts]").append(el);
  setTimeout(() => el.remove(), kind === "bad" ? 8000 : 4500);
}

function confirmBox(title, body, okLabel = "Confirm", danger = true) {
  const d = $("[data-confirm]");
  $("[data-confirm-title]").textContent = title;
  $("[data-confirm-body]").textContent = body;
  const ok = $("[data-confirm-ok]");
  ok.textContent = okLabel;
  ok.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
  d.showModal();
  return new Promise((res) => d.addEventListener("close", () => res(d.returnValue === "ok"), { once: true }));
}

const badge = (state) => {
  const map = { switched: ["Switched", "b-switched"], shadow: ["Shadow", "b-shadow"], rolled_back: ["Rolled back", "b-rolled_back"] };
  const [t, c] = map[state] || [state, ""];
  return `<span class="badge ${c}">${esc(t)}</span>`;
};
/** The gate's reason, with the jargon swapped for the words used on screen. */
const plainReason = (t) => String(t || "").replace(/frontier/g, "big model").replace(/held-out/g, "test").replace(/>=/g, "≥").replace(/sub-task/g, "job").replace(/red[- ]flag/g, "emergency");
/** Who answers this job on real calls: a two-position switch, animated when it has moved to Small. */
const gateCell = (state) => {
  const cls = state === "switched" ? "small" : state === "rolled_back" ? "back" : "";
  const note = { switched: "Small model answers", shadow: "Big model answers · small one learning", rolled_back: "Rolled back to big model" }[state] || state;
  return `<div class="gate-cell"><span class="switch ${cls}" role="img" aria-label="${esc(note)}"><span class="big">Big</span><span class="sm">Small</span></span><span class="note">${esc(note)}</span></div>`;
};
const verdict = (v) => v === null || v === undefined ? `<span class="verdict none">–</span>`
  : v ? `<span class="verdict ok">${icon("check")}Right</span>` : `<span class="verdict bad">${icon("x")}Wrong</span>`;

function empty(ico, title, text, actions = "") {
  return `<div class="empty"><div class="ico">${icon(ico)}</div><h3>${esc(title)}</h3><p>${text}</p>${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;
}
function errorState(err, retry = true) {
  return `<div class="panel">${empty("triangle-alert", "This page couldn't load", esc(err.message || "Something went wrong."),
    retry ? `<button class="btn" data-retry>${icon("refresh-cw")}Try again</button>` : "")}</div>`;
}
const skLines = (n = 6) => Array.from({ length: n }, (_, i) => `<div class="sk sk-line" style="width:${90 - (i % 3) * 18}%"></div>`).join("");
function skeletonPage(title) {
  return `<div class="ph"><div><h1>${esc(title)}</h1></div></div>
  <div class="kpis">${Array.from({ length: 5 }, () => `<div class="kpi"><div class="sk" style="height:10px;width:50%"></div><div class="sk sk-kpi"></div></div>`).join("")}</div>
  <div class="panel">${skLines(7)}</div>`;
}

function jsonHtml(obj, wrong = []) {
  if (obj === null || obj === undefined) return `<pre class="json"><span class="k">no reply</span></pre>`;
  const lines = JSON.stringify(obj, null, 2).split("\n").map((line) => {
    const m = line.match(/^(\s*)"([^"]+)":\s(.*)$/);
    if (!m) return esc(line);
    const [, ind, k, v] = m;
    const vCls = /^"/.test(v) ? "s" : /^-?\d/.test(v) ? "n" : "s";
    const html = `${ind}<span class="k">"${esc(k)}":</span> <span class="${vCls}">${esc(v)}</span>`;
    return wrong.includes(k) ? `<span class="bad-line">${html}</span>` : html;
  });
  return `<pre class="json">${lines.join("\n")}</pre>`;
}
const parse = (v) => { if (typeof v !== "string") return v; try { return JSON.parse(v); } catch { return v; } };

async function busy(btn, label, fn) {
  const html = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `${icon("loader-circle", "icon spin")}${esc(label)}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = html; }
}

const isLive = () => ctx.settings && ctx.settings.mode === "live";
async function liveGuard(what) {
  if (!isLive()) return true;
  return confirmBox(`${what} in live mode?`,
    `This sends real requests through Mubit and costs money. Kept examples count toward Mubit's ${TRIGGER}-example training trigger.`,
    "Send real calls");
}

/* ---------- shared data views ---------- */
function smallLane(t, gate) {
  const lanes = (t.heldout || []).map((h) => h.lane);
  const fromGate = (gate.version || "").split("-")[0];
  if (lanes.includes(fromGate)) return fromGate;
  return ["adapter_verified", "adapter", "shadow", "adapter_raw"].find((l) => lanes.includes(l)) || null;
}
function meter(t, gate) {
  const held = Object.fromEntries((t.heldout || []).map((h) => [h.lane, h]));
  const sl = smallLane(t, gate);
  const f = held.teacher, s = sl ? held[sl] : null;
  if (!f && !s) return `<div class="meter"><span class="faint" style="font-size:12px">Not tested yet. Run the fair test to score it.</span></div>`;
  const row = (lbl, cls, h) => `<div class="row"><span class="${cls === "f" ? "lane-frontier" : "lane-small"}">${lbl}</span><span class="track"><span class="fill ${cls}" style="width:${h ? Math.round(h.acc * 100) : 0}%"></span></span><span class="v">${h ? pct(h.acc) : "–"}</span></div>`;
  return `<div class="meter" aria-label="Test score: big model ${f ? pct(f.acc) : "not run"}, small model ${s ? pct(s.acc) : "not run"}, on ${(f || s).n} test calls">${row("Big", "f", f)}${row("Small", "s", s)}</div>`;
}
function keptRail(n) {
  const on = Math.min(n, TRIGGER);
  return `<div class="kept-rail">
    <div class="segs ${n >= TRIGGER ? "full" : ""}" aria-hidden="true">${Array.from({ length: TRIGGER }, (_, i) => `<i class="${i < on ? "on" : ""}" style="--i:${i}"></i>`).join("")}</div>
    <div class="lbl"><span>Learning examples ${tip(TIPS.rail, "tip-end")}</span><span><b>${n}</b> / ${TRIGGER}</span></div></div>`;
}

async function refreshCounts() {
  try {
    const [cor, dis] = await Promise.all([api("/api/corrections?limit=500"), api("/api/disagreements?limit=500")]);
    const fix = cor.filter((c) => c.status === "needs_human").length;
    const c1 = $('[data-count="fix"]'), c2 = $('[data-count="dis"]');
    c1.hidden = !fix; c1.textContent = fix;
    c2.hidden = !dis.length; c2.textContent = dis.length >= 500 ? "500+" : dis.length;
  } catch { /* counts are a nicety */ }
}

/* ---------- views ---------- */
const views = {};

const PHASE = { train: "Practice call", eval: "Test call", live: "Live call", keep: "Practice call", correct: "Correction", keep_correction: "Correction", chat: "Typed call", voice: "Phone call" };
function feedRow(r, isNew) {
  const tone = !r.small_runs ? "" : r.small_passed === r.small_runs ? "ok" : r.small_passed ? "warn" : "bad";
  return `<a class="feed-row ${isNew ? "new" : ""}" href="/app/calls/${encodeURIComponent(r.id)}" data-nav>
    <span class="feed-dot ${tone}" aria-hidden="true"></span>
    <span style="min-width:0"><span class="id">${esc(r.id)}</span><br><span class="what">${esc(PHASE[r.phase] || r.phase || "Call")} · ${ago(r.ts)}${r.served_small ? ` · ${r.served_small} job${r.served_small === 1 ? "" : "s"} on small` : ""}</span></span>
    <span class="lanes-mini">${r.frontier_runs ? `<span class="f" title="Big model: jobs right">Big ${r.frontier_passed}/${r.frontier_runs}</span>` : `<span class="f" title="The big model wasn't needed on this call">Big –</span>`}<span class="s" title="Small model: jobs right">Small ${r.small_passed}/${r.small_runs}</span></span></a>`;
}
function startFeed() {
  const box = $("[data-feed]");
  if (!box) return;
  let paused = false;
  const btn = $("[data-feed-pause]"), dot = $("[data-feed-dot]");
  btn?.addEventListener("click", () => {
    paused = !paused;
    btn.setAttribute("aria-pressed", String(paused));
    btn.innerHTML = paused ? `${icon("circle-play")}Resume` : `${icon("pause")}Pause`;
    dot.classList.toggle("paused", paused);
  });
  const tick = async () => {
    if (paused || document.hidden || !document.body.contains(box)) return;
    try {
      const f = await api(`/api/feed?after=${ctx.feedCursor}&limit=8`);
      if (f.rows.length) {
        box.querySelector(".empty")?.remove();
        box.insertAdjacentHTML("afterbegin", f.rows.map((r) => feedRow(r, true)).join(""));
        [...box.children].slice(12).forEach((x) => x.remove());
      }
      ctx.feedCursor = Math.max(ctx.feedCursor, f.cursor);
    } catch { /* the next tick tries again */ }
  };
  ctx.timers.push(setInterval(tick, 4000));
}

views.overview = {
  title: "Overview",
  async render() {
    const [sm, feed] = await Promise.all([api("/api/summary"), api("/api/feed?limit=10")]);
    const subs = SUBTASKS.map((k) => [k, sm.subtasks[k]]).filter(([, v]) => v);
    const switched = subs.filter(([, v]) => v.gate.state === "switched").length;
    let cmp = 0, dis = 0, fAcc = [], sAcc = [];
    for (const [, v] of subs) {
      cmp += (v.live || []).filter((l) => l.lane !== "teacher").reduce((a, l) => a + l.n, 0);
      dis += (v.disagreements || []).reduce((a, d) => a + d.n, 0);
      const held = Object.fromEntries((v.heldout || []).map((h) => [h.lane, h]));
      if (held.teacher) fAcc.push(held.teacher.acc);
      const sl = smallLane(v, v.gate);
      if (sl && held[sl]) sAcc.push(held[sl].acc);
    }
    const avg = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
    const kept = Math.max(0, ...subs.map(([, v]) => v.kept));
    const pp = sm.pence_per_call;
    const did = {
      train: subs.some(([, v]) => v.kept),
      eval: subs.some(([, v]) => (v.heldout || []).length),
      live: subs.some(([, v]) => (v.live || []).length),
    };
    const hasData = did.train || did.eval || did.live;
    const saving = pp.as_served != null && pp.all_frontier ? 1 - pp.as_served / pp.all_frontier : null;
    const lastIsNew = ctx.feedCursor;
    ctx.feedCursor = Math.max(ctx.feedCursor, feed.cursor);

    const steps = [
      ["train", "Collect learning examples", "Both models answer 120 practice calls. The checker keeps the big model's right answers and corrects its mistakes.", "audio-waveform", "Collect examples"],
      ["eval", "Run the fair test", "Both models answer test calls neither has learned from. The gate then decides, job by job, who should answer.", "flask-conical", "Run the test"],
      ["live", "Send live calls", "20 simulated phone calls arrive. Jobs that passed are answered by the small model, so the cost per call drops.", "phone-call", "Send live calls"],
    ];
    const nextKey = steps.find(([k]) => !did[k])?.[0];
    const checklist = `<div class="panel"><header><h2>${icon("list-checks")}Get started: three clicks</h2><span class="sub">${sm.mode === "live" ? "Live: real requests, real cost" : "Mock mode: simulated, free, takes seconds"}</span></header>
      <div class="checklist">${steps.map(([k, t, d, ic, lbl], i) => `<div class="check ${did[k] ? "done" : k === nextKey ? "next" : ""}">
        <span class="tick">${did[k] ? icon("check") : i + 1}</span><div><h3>${t}</h3><p>${d}</p></div>
        ${did[k] ? `<span class="faint" style="font-size:12px">Done</span>` : `<button class="btn ${k === nextKey ? "btn-primary" : ""} btn-sm" data-run="${k}">${icon(ic)}${lbl}</button>`}</div>`).join("")}</div></div>`;

    const kpi = (k, t, v, d) => `<div class="kpi"><div class="k">${k}${tip(t, "tip-down")}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;
    const kpis = `<div class="kpis">
      ${kpi("Cost per call", TIPS.cost, `${pp.as_served != null ? pence(pp.as_served) : pence(pp.all_frontier)}${pp.as_served != null ? `<small>from ${pence(pp.all_frontier)}</small>` : ""}`, saving != null ? `<span class="up">${pct(saving)} cheaper</span> over ${pp.calls} live calls` : "Big model on every job; no live calls yet")}
      ${kpi("Jobs on the small model", TIPS.switched, `${switched}<small>of ${subs.length}</small>`, switched ? `${subs.length - switched} still learning` : "None yet: all 4 still learning")}
      ${kpi("Models agree", TIPS.agree, cmp ? pct(1 - dis / cmp) : "–", cmp ? `${dis} disagreements in ${cmp} checks` : "Shows after live calls")}
      ${kpi("Small model test score", TIPS.pass, avg(sAcc) != null ? pct(avg(sAcc)) : "–", avg(fAcc) != null ? `Big model scored ${pct(avg(fAcc))}` : "Shows after the fair test")}
      ${kpi("Learning examples", TIPS.kept, `${Math.min(kept, 999)}<small>/ ${TRIGGER}</small>`, kept >= TRIGGER ? (sm.mode === "live" ? "A job has reached Mubit's trigger" : "Past the trigger (mock data)") : "Most for any one job")}
    </div>`;

    const gates = subs.map(([k, v]) => `<div class="gate-row">
        <div>${stName(k)}<div class="why">${esc(plainReason(v.gate.reason) || "Waiting for the fair test")}</div></div>
        ${gateCell(v.gate.state)}${meter(v, v.gate)}${keptRail(v.kept)}
        <a class="icon-btn" href="/app/gate" data-nav aria-label="Open ${esc(plain(k))} in the promotion gate">${icon("chevron-right")}</a></div>`).join("");

    const events = (sm.gate_events || []).slice(0, 6).map((e) => {
      const ico = e.new === "switched" ? ["arrow-right", "var(--signal)"] : e.new === "rolled_back" ? ["rotate-ccw", "var(--bad)"] : ["split", "var(--small)"];
      const said = e.new === "switched" ? "moved to the small model" : e.new === "rolled_back" ? "went back to the big model" : "is learning in the shadow";
      return `<div class="event"><svg class="icon" style="color:${ico[1]}" aria-hidden="true"><use href="/static/icons.svg#i-${ico[0]}"/></svg>
        <div><b style="font-weight:500">${esc(plain(e.subtask))}</b> <span class="faint">${said}</span><p>${esc(plainReason(e.reason))}</p></div><span class="when">${ago(e.ts)}</span></div>`;
    }).join("");

    const feedPanel = `<div class="panel"><header><h2><span class="live-dot" data-feed-dot aria-hidden="true"></span>Live call feed${tip("Newest calls first. It checks for new ones every 4 seconds. Green: the small model got every job right. Amber: some. Red: none.", "tip-down")}</h2>
        <button class="btn btn-sm btn-ghost" type="button" data-feed-pause aria-pressed="false">${icon("pause")}Pause</button></header>
      <div class="feed" data-feed>${feed.rows.length ? feed.rows.map((r) => feedRow(r, lastIsNew && r.cursor > lastIsNew)).join("") : empty("phone-incoming", "Waiting for calls", "Press <b>Send live calls</b> and they appear here as they happen.")}</div></div>`;

    const runPanel = `<div class="panel"><header><h2>${icon("play")}Run it again</h2><span class="sub">${sm.mode === "live" ? "Live: real cost" : "Mock: free"}</span></header>
      <div class="body" style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-sm" data-run="train">${icon("audio-waveform")}Collect examples</button>
        <button class="btn btn-sm" data-run="eval">${icon("flask-conical")}Run the test</button>
        <button class="btn btn-sm" data-run="live">${icon("phone-call")}Send live calls</button>
      </div></div>`;

    const flowStrip = `<div class="flow-mini" aria-label="The six steps">${["Call comes in", "Big model answers", "Small model shadows", "Checker marks both", "Mistakes corrected", "Gate decides"].map((t, i) => `<span>${i + 1}. ${t}</span>${i < 5 ? icon("chevron-right") : ""}`).join("")}<a class="btn btn-sm btn-ghost" href="/app/guide" data-nav>See how it works ${icon("arrow-right")}</a></div>`;

    content.innerHTML = `<div class="ph"><div><h1>Overview</h1><p>How far each of the 4 jobs has got towards being answered by the small model, and what a call costs.</p></div>
      <div class="actions"><a class="btn" href="/app/try" data-nav>${icon("audio-waveform")}Try a call</a><a class="btn btn-primary" href="/app/calls" data-nav>${icon("phone-call")}Browse calls</a></div></div>
      ${sm.mode !== "live" ? `<div class="notice warn" style="margin-bottom:16px">${icon("info")}<span class="grow">Mock mode. Both models are simulated, so these numbers test the pipeline. They are not results.</span></div>` : ""}
      <div style="margin-bottom:16px">${flowStrip}</div>
      ${hasData ? kpis : ""}
      ${!did.live ? `<div style="margin-bottom:16px">${checklist}</div>` : ""}
      ${hasData ? `<div class="grid g-3-1">
        <div class="stack"><div class="panel"><header><h2>${icon("layers")}The 4 jobs${tip(TIPS.switch, "tip-down")}</h2><span class="legend"><span><i style="background:var(--frontier)"></i>Big model</span><span><i style="background:var(--small)"></i>Small model</span></span></header><div class="gates">${gates}</div></div>
          <div class="panel"><header><h2>${icon("activity")}What the gate decided</h2></header>${events ? `<div class="events">${events}</div>` : empty("activity", "No decisions yet", "Run the fair test and the gate will decide each job here.", `<button class="btn btn-sm btn-primary" data-run="eval">${icon("flask-conical")}Run the test</button>`)}</div></div>
        <div class="stack">${feedPanel}${did.live ? runPanel : ""}</div>
      </div>` : ""}`;
    startFeed();
  },
};

views.calls = {
  title: "Calls",
  state: { q: "", phase: "", offset: 0 },
  async render() {
    const s = this.state, limit = 50;
    const qs = new URLSearchParams({ limit, offset: s.offset });
    if (s.q) qs.set("q", s.q);
    if (s.phase) qs.set("phase", s.phase);
    const shell = !$("[data-calls-body]");
    if (shell) {
      content.innerHTML = `<div class="ph"><div><h1>Calls</h1><p>Every call both models answered. "Right" counts are out of the call's jobs, marked by the rule checker. Click a row to open it.</p></div></div>
      <div class="panel"><div class="filters">
        <label class="search"><span class="sr-only">Search calls by id</span>${icon("search")}<input class="input" type="search" placeholder="Search call id" value="${esc(s.q)}" data-q><kbd>/</kbd></label>
        <div class="seg" role="group" aria-label="Phase">${[["", "All"], ["train", "Practice"], ["eval", "Test"], ["live", "Live"]].map(([v, l]) => `<button type="button" data-phase="${v}" aria-pressed="${s.phase === v}">${l}</button>`).join("")}</div>
      </div><div data-calls-body>${skLines(8)}</div></div>`;
      let t;
      $("[data-q]").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { s.q = e.target.value.trim(); s.offset = 0; this.render().catch(showError); }, 200); });
      $$("[data-phase]").forEach((b) => b.addEventListener("click", () => {
        s.phase = b.dataset.phase; s.offset = 0;
        $$("[data-phase]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        this.render().catch(showError);
      }));
    }
    const body = $("[data-calls-body]");
    const data = await api(`/api/calls?${qs}`);
    if (!data.rows.length) {
      body.innerHTML = s.q || s.phase ? empty("search", "No calls match", "Try a shorter id or clear the phase filter.")
        : empty("phone-call", "No calls yet", "Calls appear here once the models have answered some. The quickest start is <b>Collect examples</b>: 120 practice calls in a few seconds.", `<button class="btn btn-primary" data-run="train">${icon("audio-waveform")}Collect examples</button><a class="btn" href="/app/try" data-nav>Try one call</a>`);
      return;
    }
    const ratio = (p, n) => `<span class="ratio ${n && p === n ? "full" : p ? "part" : ""}">${p}/${n}</span>`;
    body.innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Call</th><th>Kind ${tip(TIPS.heldout, "tip-down")}</th><th>Rules</th><th>Stages</th><th>Tags</th><th class="num">Big model right</th><th class="num">Small model right</th><th class="num">Answered by small ${tip(TIPS.servedSmall, "tip-end tip-down")}</th><th class="num">Saved ${tip(TIPS.keptCol, "tip-end tip-down")}</th><th class="num">When</th></tr></thead><tbody>
      ${data.rows.map((r) => `<tr class="link" data-href="/app/calls/${encodeURIComponent(r.id)}"><td><a class="row-link" href="/app/calls/${encodeURIComponent(r.id)}" data-nav>${esc(r.id)}</a></td>
        <td>${r.split === "heldout" ? `<span class="badge b-info">test</span>` : `<span class="badge plain">${r.split === "train" ? "practice" : esc(r.split)}</span>`}</td><td class="mono">${esc(r.policy)}</td>
        <td class="faint">${r.phases.map(esc).join(", ")}</td><td><div class="tags">${r.tags.slice(0, 3).map((t) => `<span class="tag ${/red|emerg/.test(t) ? "flag" : ""}">${esc(t)}</span>`).join("")}${r.tags.length > 3 ? `<span class="tag">+${r.tags.length - 3}</span>` : ""}</div></td>
        <td class="num">${ratio(r.teacher_passed, r.teacher_runs)}</td><td class="num">${ratio(r.small_passed, r.small_runs)}</td><td class="num">${r.served_small || "–"}</td><td class="num">${r.kept || "–"}</td><td class="num faint">${ago(r.ts)}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="pager"><span>${s.offset + 1}–${s.offset + data.rows.length} of ${data.total.toLocaleString("en-GB")}</span><span style="display:flex;gap:6px">
        <button class="btn btn-sm" data-page="-1" ${s.offset === 0 ? "disabled" : ""}>Previous</button><button class="btn btn-sm" data-page="1" ${s.offset + limit >= data.total ? "disabled" : ""}>Next</button></span></div>`;
    $$("[data-page]", body).forEach((b) => b.addEventListener("click", () => { s.offset = Math.max(0, s.offset + Number(b.dataset.page) * limit); this.render().catch(showError); }));
    $$("tr[data-href]", body).forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("a")) go(tr.dataset.href); }));
  },
};

views.call = {
  title: "Call",
  async render(id) {
    const c = await api(`/api/calls/${encodeURIComponent(id)}`);
    setCrumbs([["Calls", "/app/calls"], [c.id]]);
    const turns = (c.transcript || []).map((t) => `<div class="turn ${t.role === "caller" ? "caller" : ""}"><span class="speaker">${t.role === "caller" ? "Caller" : "Receptionist"}</span><p>${esc(t.text)}</p></div>`).join("");
    const laneName = (kind) => kind === "frontier" ? "Big model" : "Small model";
    const laneCard = (v, kind, truth) => {
      if (!v) return `<div class="lane-card ${kind}"><header><span class="${kind === "frontier" ? "lane-frontier" : "lane-small"}">${laneName(kind)}</span></header><div class="lane-empty">${icon("info")}<span>${kind === "frontier" ? "Not run on this call. Once a job is switched, the big model only spot-checks some calls." : "The small model didn't answer this job on this call."}</span></div></div>`;
      return `<div class="lane-card ${kind}"><header><span class="${kind === "frontier" ? "lane-frontier" : "lane-small"}">${laneName(kind)} <span class="faint">· ${kind === "frontier" ? "what the caller heard" : v.served ? "answered for real" : "shadow only"}</span></span>
        <span style="display:flex;gap:10px;align-items:center">${v.served ? `<span class="badge b-switched">answered caller</span>` : ""}${v.kept ? `<span class="badge b-ok">saved to learn</span>` : ""}<span class="meta">${v.latency_ms ? Math.round(v.latency_ms) + " ms" : ""}</span>${verdict(v.passed)}</span></header>
        ${jsonHtml(v.output, v.wrong || [])}${v.wrong && v.wrong.length ? `<div class="wrong">${v.wrong.map((w) => `<span>${icon("x", "icon")} <b class="mono">${esc(w)}</b> doesn't match the rules</span>`).join("")}</div>` : ""}</div>`;
    };
    const blocks = SUBTASKS.filter((t) => c.subtasks[t]).map((t) => {
      const s = c.subtasks[t];
      const agree = s.frontier && s.small ? s.frontier.passed === s.small.passed : null;
      return `<section class="st-block"><div class="st-head"><h3>${stName(t)}</h3>${agree === null ? "" : agree ? `<span class="badge plain">both agree</span>` : `<span class="badge b-warn">they disagree</span>`}
        ${s.corrections.map((x) => `<span class="badge ${(STATUS[x.status] || ["", ""])[1]}">${esc((STATUS[x.status] || [x.status])[0])}</span>`).join("")}<span class="sp"></span>
        ${s.truth ? `<button class="btn btn-sm btn-ghost" data-truth="${t}" aria-expanded="false">${icon("shield-check")}What the rules expect</button>` : ""}</div>
        <div class="lanes">${laneCard(s.frontier, "frontier")}${laneCard(s.small, "small")}</div>
        ${s.truth ? `<div class="lanes" data-truth-body="${t}" hidden><div class="lane-card" style="grid-column:1/-1"><header><span>${icon("shield-check")} The right answer under rules ${esc(c.policy)}</span></header>${jsonHtml(s.truth)}</div></div>` : ""}</section>`;
    }).join("");
    content.innerHTML = `<div class="ph"><div><h1 class="mono">${esc(c.id)}</h1><p>${c.split === "heldout" ? "A test call: never used for learning, only to score the models fairly." : "A practice call: checked answers from it can become learning examples."}</p></div>
      <div class="actions"><a class="btn" href="/app/calls" data-nav>${icon("arrow-left")}All calls</a></div></div>
      <div class="call-grid"><div class="panel"><dl class="dl"><dt>Kind</dt><dd>${c.split === "heldout" ? "test" : c.split === "train" ? "practice" : esc(c.split)}</dd><dt>Rules</dt><dd>${esc(c.policy)}</dd><dt>Last activity</dt><dd>${ago(c.ts)}</dd><dt>Tags</dt><dd><div class="tags" style="justify-content:flex-end">${c.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("") || "–"}</div></dd></dl>
        <header style="border-top:0"><h2>${icon("audio-waveform")}Transcript</h2></header>${turns ? `<div class="transcript">${turns}</div>` : empty("audio-waveform", "Transcript not stored", "This call came from a pool that is no longer loaded.")}</div>
        <div class="panel"><header><h2>${icon("split")}The 4 jobs</h2><span class="sub">Big model vs small model, marked by the rule checker</span></header>${blocks}</div></div>`;
    $$("[data-truth]").forEach((b) => b.addEventListener("click", () => {
      const el = $(`[data-truth-body="${b.dataset.truth}"]`); el.hidden = !el.hidden; b.setAttribute("aria-expanded", String(!el.hidden));
    }));
  },
};

views.disagreements = {
  title: "Disagreements",
  filter: "",
  async render() {
    const rows = await api("/api/disagreements?limit=200");
    const f = this.filter;
    const list = rows.filter((r) => !f || r.who_right === f);
    const who = { teacher: ["Big model right", "b-info"], shadow: ["Small model right", "b-switched"], neither: ["Both wrong", "b-bad"] };
    content.innerHTML = `<div class="ph"><div><h1>Disagreements</h1><p>Calls where only one model got a job right. "Small model right" rows are the big model's own mistakes.</p></div>
      <div class="seg" role="group" aria-label="Who was right">${[["", "All"], ["teacher", "Big model right"], ["shadow", "Small model right"]].map(([v, l]) => `<button type="button" data-f="${v}" aria-pressed="${f === v}">${l}</button>`).join("")}</div></div>
      <div class="panel">${list.length ? `<div class="items">${list.map((r) => {
        const [wl, wc] = who[r.who_right] || [r.who_right, ""];
        return `<article class="item"><div class="item-head"><b style="font-weight:600">${esc(plain(r.subtask))}</b><a class="row-link mono" style="color:var(--fg-2)" href="/app/calls/${encodeURIComponent(r.scenario_id)}" data-nav>${esc(r.scenario_id)}</a><span class="badge ${wc}">${esc(wl)}</span><span class="sp"></span><span class="faint" style="font-size:12px">policy ${esc(r.policy_version)} · ${ago(r.ts)}</span></div>
          <div class="diff3"><div><h4><span class="lane-frontier">Big model</span>${verdict(!!r.teacher_ok)}</h4>${jsonHtml(r.teacher)}</div><div><h4><span class="lane-small">Small model</span>${verdict(!!r.shadow_ok)}</h4>${jsonHtml(r.shadow)}</div><div><h4><span>The right answer</span>${icon("shield-check")}</h4>${jsonHtml(r.truth)}</div></div></article>`;
      }).join("")}</div>` : empty("git-compare", f ? "Nothing in this filter" : "No disagreements yet", f ? "Clear the filter to see every disagreement." : "When only one model gets a job right on a live call, it shows up here with both answers and the right one. Send some live calls to fill it.", f ? "" : `<button class="btn btn-primary" data-run="live">${icon("phone-call")}Send live calls</button>`)}</div>`;
    $$("[data-f]").forEach((b) => b.addEventListener("click", () => { this.filter = b.dataset.f; this.render().catch(showError); }));
  },
};

views.corrections = {
  title: "Corrections",
  filter: "needs_human",
  async render() {
    const rows = await api("/api/corrections?limit=300");
    const f = this.filter;
    const kept = (r) => r.status.startsWith("kept") || r.status === "human_fixed";
    const list = rows.filter((r) => (f === "needs_human" ? r.status === "needs_human" : f === "kept" ? kept(r) : true));
    const nHuman = rows.filter((r) => r.status === "needs_human").length;
    content.innerHTML = `<div class="ph"><div><h1>Corrections</h1><p>When the big model gets a job wrong, it is shown the checker's note and answers again. Fixes it can't make wait here for a person to approve.</p></div>
      <div class="actions"><a class="btn" href="/api/corrections/export" download="shadowcall-corrections.json">${icon("download")}Export fixes</a></div></div>
      <div class="panel"><div class="filters"><div class="seg" role="group" aria-label="Status">${[["needs_human", `Needs a person · ${nHuman}`], ["kept", "Fixed"], ["", "All"]].map(([v, l]) => `<button type="button" data-f="${v}" aria-pressed="${f === v}">${esc(l)}</button>`).join("")}</div></div>
      ${list.length ? `<div class="items">${list.map((r) => {
        const [sl, sc] = STATUS[r.status] || [r.status, ""];
        const bad = parse(r.bad), fixed = parse(r.fixed);
        const wrongKeys = bad && fixed && typeof bad === "object" ? Object.keys(fixed).filter((k) => JSON.stringify(bad[k]) !== JSON.stringify(fixed[k])) : [];
        const finding = (r.note || "").split("\n").filter((l) => l.startsWith("- ")).map((l) => l.slice(2));
        return `<article class="item" data-id="${r.id}"><div class="item-head"><b style="font-weight:600">${esc(plain(r.subtask))}</b><a class="row-link mono" style="color:var(--fg-2)" href="/app/calls/${encodeURIComponent(r.scenario_id)}" data-nav>${esc(r.scenario_id)}</a><span class="badge ${sc}">${esc(sl)}</span><span class="sp"></span><span class="faint" style="font-size:12px">${r.attempts} attempt${r.attempts === 1 ? "" : "s"} · ${ago(r.ts)}</span></div>
          ${finding.length ? `<div class="notice info">${icon("shield-check")}<span class="grow">${finding.map(esc).join("<br>")}</span></div>` : ""}
          <div class="diff3" style="grid-template-columns:1fr 1fr"><div><h4><span class="lane-frontier">Big model said</span>${verdict(false)}</h4>${jsonHtml(bad, wrongKeys)}</div><div><h4><span>Suggested fix</span>${r.source ? `<span class="faint">${esc(r.source)}</span>` : ""}</h4>${jsonHtml(fixed)}</div></div>
          ${r.status === "needs_human" ? `<details><summary class="faint" style="cursor:pointer;font-size:13px">Edit the repair before approving</summary><label class="sr-only" for="fx-${r.id}">Corrected reply JSON</label><textarea class="input" id="fx-${r.id}" spellcheck="false" style="margin-top:8px">${esc(JSON.stringify(fixed, null, 2))}</textarea></details>
          <div class="fix-actions"><button class="btn btn-primary btn-sm" data-approve="${r.id}">${icon("check")}Approve fix</button><span class="faint" style="font-size:12px">Saved here as the right answer for this call. Nothing is sent to Mubit.</span></div>` : ""}</article>`;
      }).join("")}</div>` : empty(f === "needs_human" ? "circle-check" : "wrench", f === "needs_human" ? "Nothing needs a person" : "No corrections yet", f === "needs_human" ? (rows.length ? "The big model fixed every mistake itself after seeing the checker's note. Open <b>Fixed</b> to see them." : "Corrections appear when the big model gets a job wrong while collecting examples.") : "Corrections appear when the big model gets a job wrong while collecting examples.", rows.length ? "" : `<button class="btn btn-primary" data-run="train">${icon("audio-waveform")}Collect examples</button>`)}</div>`;
    $$("[data-f]").forEach((b) => b.addEventListener("click", () => { this.filter = b.dataset.f; this.render().catch(showError); }));
    $$("[data-approve]").forEach((b) => b.addEventListener("click", async () => {
      const id = b.dataset.approve, ta = $(`#fx-${id}`);
      let fixed;
      try { fixed = JSON.parse(ta.value); } catch { ta.closest("details").open = true; ta.setAttribute("aria-invalid", "true"); toast("That JSON doesn't parse", "Fix the edited reply, then approve.", "bad"); return; }
      await busy(b, "Approving…", async () => {
        try {
          await api(`/api/corrections/${id}/approve`, { method: "POST", body: { fixed, by: ctx.me?.user?.email || "staff" } });
          toast("Fix approved", "It now counts as gold for this call.");
          refreshCounts();
          await this.render();
        } catch (e) { toast("Couldn't approve", e.message, "bad"); }
      });
    }));
  },
};

views.gate = {
  title: "Promotion gate",
  async render() {
    const sm = await api("/api/summary");
    const g = ctx.settings?.gate || {};
    const rows = SUBTASKS.filter((k) => sm.subtasks[k]).map((k) => {
      const v = sm.subtasks[k], st = v.gate.state;
      return `<div class="gate-row"><div>${stName(k)}<div class="why">${esc(plainReason(v.gate.reason) || "Waiting for the fair test")}</div><div class="ver">${v.gate.since ? `since ${ago(v.gate.since)}` : ""}${v.gate.version ? ` · ${esc(v.gate.version)}` : ""}</div></div>
        ${gateCell(st)}${meter(v, v.gate)}${keptRail(v.kept)}
        <div style="display:flex;gap:6px;justify-content:flex-end">${st === "switched" ? `<button class="btn btn-sm btn-danger" data-act="rollback" data-t="${k}">${icon("rotate-ccw")}Roll back</button>`
          : st === "rolled_back" ? `<button class="btn btn-sm" data-act="shadow" data-t="${k}">${icon("split")}Back to shadow</button>` : `<span class="faint" style="font-size:12px">Learning</span>`}</div></div>`;
    }).join("");
    content.innerHTML = `<div class="ph"><div><h1>Promotion gate</h1><p>A job moves to the small model only when it scores at least as well as the big model on ${g.min_heldout ?? 20}+ test calls, with no missed emergencies. The big model still spot-checks ${Math.round((g.audit_rate ?? 0.2) * 100)}% of switched calls.</p></div>
      <div class="actions"><button class="btn" data-run="eval">${icon("flask-conical")}Re-run the fair test</button></div></div>
      <div class="panel"><header><h2>${icon("layers")}The 4 jobs${tip(TIPS.meter, "tip-down")}</h2><span class="legend"><span><i style="background:var(--frontier)"></i>Big model</span><span><i style="background:var(--small)"></i>Small model</span></span></header><div class="gates">${rows}</div></div>
      <p class="faint" style="font-size:12px;margin-top:12px">Safety net: a switched job goes back to the big model if its spot-check score drops below ${pct(g.rollback_floor ?? 0)} over the last ${g.rollback_window ?? "–"} checks, or whenever the rules change.</p>`;
    $$("[data-act]").forEach((b) => b.addEventListener("click", async () => {
      const { act, t } = b.dataset;
      if (act === "rollback" && !(await confirmBox(`Roll back ${t}?`, "The big model takes this job back on every call straight away. The small model keeps learning and must pass the test again to return.", "Roll back"))) return;
      await busy(b, act === "rollback" ? "Rolling back…" : "Updating…", async () => {
        try { await api(`/api/gate/${t}/${act}`, { method: "POST" }); toast(act === "rollback" ? `${t} rolled back` : `${t} is shadowing again`); await this.render(); }
        catch (e) { toast("Gate action failed", e.message, "bad"); }
      });
    }));
  },
};

function diffHtml(diff) {
  const out = [];
  let i = 0;
  while (i < diff.length) {
    if (diff[i].op !== "same") { out.push(`<div class="${diff[i].op}">${esc(diff[i].text) || " "}</div>`); i++; continue; }
    let j = i; while (j < diff.length && diff[j].op === "same") j++;
    const run = diff.slice(i, j), head = i === 0 ? 0 : 2, tail = j === diff.length ? 0 : 2;
    if (run.length > head + tail + 2) {
      run.slice(0, head).forEach((d) => out.push(`<div>${esc(d.text) || " "}</div>`));
      out.push(`<div class="gap">${run.length - head - tail} unchanged lines</div>`);
      run.slice(run.length - tail).forEach((d) => out.push(`<div>${esc(d.text) || " "}</div>`));
    } else run.forEach((d) => out.push(`<div>${esc(d.text) || " "}</div>`));
    i = j;
  }
  return out.join("");
}

views.policy = {
  title: "Policy",
  async render() {
    const p = await api("/api/policy");
    const target = p.active === "v1" ? "v2" : "v1";
    const adds = p.diff.filter((d) => d.op === "add").length, dels = p.diff.filter((d) => d.op === "del").length;
    content.innerHTML = `<div class="ph"><div><h1>Policy</h1><p>The practice's booking rules. The checker marks both models against the active version, so changing it sends every switched job back to the big model until it passes again.</p></div></div>
      <div class="grid g-3-1"><div class="panel"><header><h2>${icon("git-compare")}v1 → v2</h2><span class="sub"><span style="color:var(--ok)">+${adds}</span> <span style="color:var(--bad)">−${dels}</span> lines · active <b class="mono" style="color:var(--fg)">${esc(p.active)}</b></span></header><div class="pdiff">${diffHtml(p.diff)}</div></div>
      <div class="stack"><div class="panel"><header><h2>${icon("refresh-cw")}Fast refresh</h2></header><div class="body" style="display:grid;gap:12px">
        <p class="muted" style="font-size:14px">Switch to <b class="mono" style="color:var(--fg)">${target}</b> and re-qualify in one go:</p>
        <ol style="margin:0;padding-left:18px;display:grid;gap:6px;font-size:13px;color:var(--fg-2)"><li>Switched jobs go back to the big model.</li><li>Both models answer practice calls under ${target}; checked answers are saved.</li><li>The fair test runs again under ${target}.</li><li>The gate switches back whatever passes.</li></ol>
        ${isLive() ? `<div class="notice warn">${icon("triangle-alert")}<span class="grow">Live mode: this sends real calls and can push a task past ${TRIGGER} kept examples.</span></div>` : ""}
        <button class="btn btn-primary" data-refresh="${target}">${icon("refresh-cw")}Switch to ${target} and re-qualify</button>
        <div data-refresh-out></div></div></div>
        <div class="panel"><header><h2>${icon("scroll-text")}Active text</h2><span class="sub mono">${esc(p.active)}</span></header><pre class="json" style="max-height:340px">${esc(p.versions[p.active])}</pre></div></div></div>`;
    $("[data-refresh]").addEventListener("click", async (e) => {
      const b = e.currentTarget, v = b.dataset.refresh;
      const live = isLive();
      if (!(await confirmBox(`Switch policy to ${v}?`, live ? `Real calls go through Mubit. Kept examples can reach Mubit's ${TRIGGER}-example training trigger.` : "Switched jobs go back to the big model until they pass the test on the new rules. Mock mode: no cost.", `Switch to ${v}`, live))) return;
      await busy(b, "Re-qualifying…", async () => {
        try {
          const r = await api("/api/refresh", { method: "POST", body: { version: v, confirm_live: live } });
          toast(`Policy ${v} is active`, `${r.trained_calls} training calls, gate re-run.`);
          await views.policy.render();
          $("[data-refresh-out]").innerHTML = `<table class="tbl"><thead><tr><th>Job</th><th>Rolled back</th><th>Gate</th></tr></thead><tbody>${Object.entries(r.gate).map(([t, d]) => `<tr><td>${esc(plain(t))}</td><td>${r.rollbacks[t] ? "yes" : "–"}</td><td class="wrap">${d.promote ? badge("switched") : badge("shadow")} <span class="faint" style="font-size:12px">${esc(d.reason)}</span></td></tr>`).join("")}</tbody></table>`;
          loadPills();
        } catch (err) { toast("Refresh failed", err.message, "bad"); }
      });
    });
  },
};

function chart(rep) {
  const lanes = Object.keys(LANES);
  const subs = SUBTASKS.filter((t) => rep.subtasks[t]);
  const W = 760, H = 280, L = 40, B = 36, T = 12, gw = (W - L - 8) / subs.length, bw = Math.min(26, (gw - 28) / lanes.length);
  let g = "";
  for (const y of [0, 0.25, 0.5, 0.75, 1]) {
    const yy = T + (H - T - B) * (1 - y);
    g += `<line class="${y ? "grid-l" : "axis"}" x1="${L}" x2="${W - 8}" y1="${yy}" y2="${yy}"/><text x="${L - 8}" y="${yy + 4}" text-anchor="end">${y * 100}%</text>`;
  }
  subs.forEach((t, i) => {
    const x0 = L + i * gw + (gw - bw * lanes.length - 4 * (lanes.length - 1)) / 2;
    lanes.forEach((ln, j) => {
      const d = rep.subtasks[t][ln];
      if (!d || !d.available || d.accuracy == null) return;
      const h = (H - T - B) * d.accuracy, x = x0 + j * (bw + 4), y = T + (H - T - B) - h;
      g += `<rect x="${x}" y="${y}" width="${bw}" height="${h}" rx="2" fill="${LANES[ln].color}"><title>${plain(t)} · ${LANES[ln].label}: ${pct(d.accuracy, 1)}</title></rect>`;
    });
    g += `<text class="lbl" x="${L + i * gw + gw / 2}" y="${H - 12}" text-anchor="middle">${plain(t)}</text>`;
  });
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Test score per job for each version">${g}</svg></div>`;
}

const LIVE_LANES = { teacher: "Big model (frontier)", shadow: "Small model, untrained" };

function liveDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? esc(iso) : esc(d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London", timeZoneName: "short" }));
}

function livePanel(lr) {
  if (!lr || !lr.evals || !Object.keys(lr.evals).length) return "";
  return Object.entries(lr.evals).map(([phase, ev]) => {
    const ns = new Set();
    const rows = SUBTASKS.filter((t) => ev.subtasks[t]).map((t) => Object.keys(LIVE_LANES).map((l, i) => {
      const d = ev.subtasks[t][l] || {};
      ns.add(d.n);
      const small = d.n != null && d.n < 20 ? ` <span class="badge b-warn" title="Fewer than 20 calls: treat as a rough signal">small n</span>` : "";
      return `<tr>${i === 0 ? `<td rowspan="2" style="vertical-align:top;padding-top:12px">${stName(t)}</td>` : ""}<td>${LIVE_LANES[l]}</td>
        <td class="num">${d.accuracy == null ? "–" : pct(d.accuracy, 1)} <span class="faint">(${d.passed ?? "–"}/${d.n ?? "–"})</span>${small}</td>
        <td class="num">${d.median_latency_ms == null ? "–" : Math.round(d.median_latency_ms) + " ms"}</td>
        <td class="num">${d.median_pence == null ? "–" : pence(d.median_pence)}</td>
        <td class="num">${d.red_flag_n ? `${d.red_flag_misses} missed of ${d.red_flag_n}` : "–"}</td></tr>`;
    }).join("")).join("");
    return `<div class="panel" data-live-results><header><h2>${icon("activity")}${esc(lr.label || "Live — real Mubit calls")}</h2><span class="badge b-ok">live</span></header>
      <div class="body"><p class="faint" style="margin:0 0 6px">${esc(phase.replace("eval_", "Run: "))} · ${liveDate(ev.from_utc)} to ${liveDate(ev.to_utc)} · ${[...ns].filter((x) => x != null).join(", ")} unseen test calls per job · big model <span class="mono">${esc(lr.teacher_model)}</span>, small model <span class="mono">${esc(lr.shadow_model)}</span> · marked by our own checker, not by the big model.</p>
      <p class="faint" style="margin:0">Pence: ${esc(lr.pence_note || "")}. Saved ${liveDate(lr.generated_utc)}.</p></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Job</th><th>Version</th><th class="num">Score (right/total)</th><th class="num">Median speed</th><th class="num">Median pence</th><th class="num">Emergencies</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }).join("") + (lr.findings?.length ? `<div class="panel"><header><h2>${icon("info")}What to know about these live numbers</h2></header><div class="body"><ul style="margin:0;padding-left:18px">${lr.findings.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div></div>` : "");
}

views.evaluation = {
  title: "Evaluation",
  async render() {
    const [rep, lr] = await Promise.all([api("/api/eval/report"), api("/api/live-results").catch(() => ({}))]);
    const live = livePanel(lr);
    const has = rep && rep.subtasks && Object.keys(rep.subtasks).length;
    const head = `<div class="ph"><div><h1>Evaluation</h1><p>The same unseen test calls through four versions: the big model, the small model untrained, and the small model trained on every answer or only on answers the checker approved.</p></div>
      <div class="actions"><button class="btn btn-primary" data-run="eval">${icon("flask-conical")}${has ? "Re-run the test" : "Run the fair test"}</button></div></div>`;
    if (!has) { content.innerHTML = head + (live ? `<div class="stack" style="margin-bottom:16px">${live}</div>` : "") + `<div class="panel">${empty("flask-conical", "No test results yet", "Run the fair test to compare all four versions on calls none of them learned from. In mock mode it takes a few seconds and costs nothing.", `<button class="btn btn-primary" data-run="eval">${icon("flask-conical")}Run the fair test</button>`)}</div>`; return; }
    const lanes = Object.keys(LANES);
    const rows = SUBTASKS.filter((t) => rep.subtasks[t]).map((t) => {
      const best = Math.max(...lanes.map((l) => rep.subtasks[t][l]?.accuracy ?? -1));
      return lanes.map((l, i) => {
        const d = rep.subtasks[t][l] || {};
        const ok = d.available !== false && d.accuracy != null;
        return `<tr>${i === 0 ? `<td rowspan="${lanes.length}" style="vertical-align:top;padding-top:12px">${stName(t)}</td>` : ""}<td><span style="display:inline-flex;align-items:center;gap:8px"><i style="width:8px;height:8px;border-radius:2px;background:${LANES[l].color}"></i>${LANES[l].label}</span></td>
          <td class="num ${ok && d.accuracy === best ? "best" : ""}">${ok ? pct(d.accuracy, 1) : "n/a"}</td><td class="num">${ok ? pence(d.pence_per_call) : "–"}</td><td class="num">${ok && d.latency_ms ? Math.round(d.latency_ms) + " ms" : "–"}</td><td class="num">${d.red_flag_accuracy == null ? "–" : pct(d.red_flag_accuracy)}</td><td class="num faint">${d.n ?? "–"}</td></tr>`;
      }).join("");
    }).join("");
    content.innerHTML = head + (live ? `<div class="stack" style="margin-bottom:16px">${live}</div>` : "") + (rep.mode !== "live" ? `<div class="notice warn" style="margin-bottom:16px">${icon("info")}<span class="grow">Mock mode: the table below is simulated. Use it to check the pipeline, not to quote results.${live ? " The live panel above is real." : ""}</span></div>` : "") +
      `<div class="stack"><div class="panel"><header><h2>${icon("activity")}Test score by job${tip(TIPS.meter, "tip-down")}</h2><span class="legend">${lanes.map((l) => `<span><i style="background:${LANES[l].color}"></i>${LANES[l].label}</span>`).join("")}</span></header><div class="body">${chart(rep)}</div></div>
      <div class="panel"><header><h2>${icon("flask-conical")}Full table</h2><span class="sub">${rep.n_heldout} test calls · marked by the rule checker</span></header><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Job</th><th>Version</th><th class="num">Score</th><th class="num">Pence / call ${tip(TIPS.cost, "tip-down")}</th><th class="num">Speed ${tip(TIPS.latency, "tip-down")}</th><th class="num">Emergencies caught ${tip(TIPS.red, "tip-end tip-down")}</th><th class="num">Calls ${tip(TIPS.n, "tip-end tip-down")}</th></tr></thead><tbody>${rows}</tbody></table></div></div></div>`;
  },
};

views.settings = {
  title: "Settings",
  async render() {
    const s = await api("/api/settings");
    ctx.settings = s;
    const kv = (o, fmt = (v) => esc(v ?? "–")) => `<dl class="kv">${Object.entries(o).map(([k, v]) => `<div><dt>${esc(k.replaceAll("_", " "))}</dt><dd>${fmt(v, k)}</dd></div>`).join("")}</dl>`;
    const keyState = (v) => v ? `<span class="key-state yes">${icon("circle-check")}Set</span>` : `<span class="key-state no">${icon("circle-x")}Not set</span>`;
    content.innerHTML = `<div class="ph"><div><h1>Settings</h1><p>Read from the server's environment. Change them in <span class="mono">.env</span> and restart. Key values are never sent to the browser.</p></div></div>
      <div class="grid g-2">
        <div class="panel"><header><h2>${icon("cpu")}Mode and models</h2>${s.mode === "live" ? `<span class="badge b-ok">live</span>` : `<span class="badge b-warn">mock</span>`}</header>${kv({ mode: s.mode, active_policy: s.policy, frontier_model: s.models.frontier, small_model: s.models.small_label || s.models.small, adapter_model: s.models.adapter || "not configured" })}</div>
        <div class="panel"><header><h2>${icon("key-round")}Keys</h2><span class="sub">present or not, never the value</span></header>${kv(s.keys, (v) => keyState(v))}</div>
        <div class="panel"><header><h2>${icon("layers")}Gate</h2></header>${kv(s.gate)}</div>
        <div class="panel"><header><h2>${icon("wrench")}Learning</h2></header>${kv(s.learning)}</div>
        <div class="panel"><header><h2>${icon("activity")}Prices (pence per million tokens)</h2></header>${kv(s.prices_pence_per_mtok)}</div>
        <div class="panel"><header><h2>${icon("shield-check")}Access</h2></header>${kv({ sign_in_required: s.auth.enabled ? "yes" : "no", sign_up: s.auth.signup_open ? "open" : "closed", demo_account: s.auth.demo_account ? "configured" : "not configured", signed_in_as: ctx.me?.user?.email || "–" })}</div>
        <div class="panel" style="grid-column:1/-1"><header><h2>${icon("external-link")}Endpoints</h2></header>${kv(s.endpoints, (v) => esc(v || "–"))}</div>
      </div>`;
  },
};


views.try = {
  title: "Try a call",
  picked: null,
  async render() {
    const cards = await api("/api/cards?n=12");
    if (!cards.length) { content.innerHTML = `<div class="panel">${empty("phone-call", "No call cards", "The scenario pool is empty for this policy.")}</div>`; return; }
    const cur = cards.find((c) => c.id === this.picked) || cards[0];
    this.picked = cur.id;
    content.innerHTML = `<div class="ph"><div><h1>Try a call</h1><p>Pick a call card on the left, then press <b>Run through both models</b>. You can edit what the caller says first.</p></div></div>
      <div class="grid g-3-1" style="grid-template-columns:minmax(260px,1fr) minmax(0,2fr)">
        <div class="panel"><header><h2>${icon("scroll-text")}Call cards</h2><span class="sub">policy ${esc(ctx.settings?.policy || "")}</span></header>
          <div class="items">${cards.map((c) => `<button type="button" class="item" data-card="${esc(c.id)}" style="text-align:left;background:${c.id === cur.id ? "var(--ink-3)" : "transparent"};border:0;border-top:1px solid var(--line);color:inherit;cursor:pointer" aria-pressed="${c.id === cur.id}">
            <span class="mono" style="font-size:13px">${esc(c.id)}</span><span class="tags">${c.tags.map((t) => `<span class="tag ${/red|emerg/.test(t) ? "flag" : ""}">${esc(t)}</span>`).join("")}</span></button>`).join("")}</div></div>
        <div class="stack">
          <div class="panel"><header><h2>${icon("audio-waveform")}Script for ${esc(cur.id)}</h2><button class="btn btn-sm" data-demo>${icon("phone-call")}Use for the next phone call</button></header>
            <div class="body"><label class="sr-only" for="lines">Caller lines, one per line</label><textarea class="input" id="lines" spellcheck="false">${esc(cur.script.join("\n"))}</textarea>
            <div class="fix-actions" style="margin-top:10px"><button class="btn btn-primary" data-chat>${icon("play")}Run through both models</button><span class="faint" style="font-size:12px">One line per caller turn. Edit freely; the card's truth still scores it.${isLive() ? " Live mode: costs real tokens." : ""}</span></div></div></div>
          <div class="panel" data-chat-out><header><h2>${icon("split")}Result</h2></header>${empty("play", "Nothing run yet", "Press <b>Run through both models</b>. Each job's mark for both models appears here in a few seconds.")}</div>
        </div></div>`;
    $$("[data-card]").forEach((b) => b.addEventListener("click", () => { this.picked = b.dataset.card; this.render().catch(showError); }));
    $("[data-demo]").addEventListener("click", async (e) => {
      await busy(e.currentTarget, "Selecting…", async () => {
        try { await api(`/api/demo-card/${encodeURIComponent(cur.id)}`, { method: "POST" }); toast("Card selected for the phone demo", "The next real call is scored against this card."); }
        catch (err) { toast("Couldn't select the card", err.message, "bad"); }
      });
    });
    $("[data-chat]").addEventListener("click", async (e) => {
      if (!(await liveGuard("Run a text call"))) return;
      const lines = $("#lines").value.split("\n").map((l) => l.trim()).filter(Boolean);
      await busy(e.currentTarget, "Running…", async () => {
        try {
          const r = await api("/api/chat", { method: "POST", body: { card_id: cur.id, caller_lines: lines } });
          $("[data-chat-out]").innerHTML = `<header><h2>${icon("split")}Result</h2><a class="btn btn-sm btn-ghost" href="/app/calls/${encodeURIComponent(r.card)}" data-nav>Open call ${icon("arrow-right")}</a></header>
            <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Job</th><th>Caller heard</th><th>Big model</th><th>Small model</th><th class="num">Big ms</th><th class="num">Small ms</th></tr></thead><tbody>
            ${r.subtasks.map((x) => `<tr><td>${stName(x.subtask)}</td><td>${x.served_by === "teacher" ? `<span class="lane lane-frontier">big model</span>` : `<span class="lane lane-small">small model</span>`}</td><td>${verdict(x.teacher_ok)}</td><td>${verdict(x.shadow_ok)}</td><td class="num">${Math.round(x.latency_teacher) || "–"}</td><td class="num">${Math.round(x.latency_shadow) || "–"}</td></tr>`).join("")}</tbody></table></div>`;
          refreshCounts();
        } catch (err) { toast("Run failed", err.message, "bad"); }
      });
    });
  },
};

views.guide = {
  title: "How it works",
  async render() {
    const pages = [
      ["overview", "layout-dashboard", "Overview", "The scoreboard: cost per call, which jobs have switched, and a live call feed."],
      ["calls", "phone-call", "Calls", "Every call. Open one to see both models' answers side by side."],
      ["disagreements", "git-compare", "Disagreements", "Calls where only one model was right. This is the evidence."],
      ["corrections", "wrench", "Corrections", "The big model's mistakes, how they were fixed, and any that need a person."],
      ["gate", "layers", "Promotion gate", "One switch per job: big model or small model, with the reason and a rollback button."],
      ["policy", "scroll-text", "Policy", "The practice's booking rules. Change them and every switch goes back to safe."],
      ["evaluation", "flask-conical", "Evaluation", "The fair test: four versions on calls none of them learned from."],
      ["try", "audio-waveform", "Try a call", "Run one call yourself and watch the whole loop."],
    ];
    const look = [
      ["scale", "Is the test fair?", "The small model is scored on test calls it never learned from, by a checker that is plain code."],
      ["shield-check", "Is it safe?", "One missed emergency blocks a switch. Changing the rules switches everything back. Rollback is one click."],
      ["sparkles", "Does it learn from mistakes?", "The big model's wrong answers are corrected before they become lessons, so the small model doesn't copy them."],
      ["badge-check", "Is it honest?", "Mock mode says so on every page. Real Mubit training only starts at 25 checked examples per job."],
    ];
    content.innerHTML = `<div class="ph"><div><h1>How it works</h1><p>ShadowCall in six steps. Click a step, or let it play.</p></div>
      <div class="actions"><button class="btn" type="button" data-tour-again>${icon("compass")}Take the tour</button><a class="btn btn-primary" href="/app" data-nav>${icon("layout-dashboard")}Go to overview</a></div></div>
      <div class="panel" style="margin-bottom:16px"><header><h2>${icon("route")}What happens to every call</h2><span class="sub">Steps 2 and 3 happen at the same time</span></header><div class="body" data-flow-root>${flowHtml()}</div></div>
      <div class="grid g-2" style="margin-bottom:16px">
        <div class="panel"><header><h2>${icon("compass")}What each page is for</h2></header><div class="body"><div class="gloss">${pages.map(([r, ic, t, d]) => `<a class="gloss-item" href="${r === "overview" ? "/app" : "/app/" + r}" data-nav><h3>${icon(ic)}${t}</h3><p>${d}</p></a>`).join("")}</div></div></div>
        <div class="panel"><header><h2>${icon("ear")}What to look for when judging</h2></header><div class="body"><div class="gloss">${look.map(([ic, t, d]) => `<div class="gloss-item"><h3>${icon(ic)}${t}</h3><p>${d}</p></div>`).join("")}</div></div></div>
      </div>
      <div class="panel"><header><h2>${icon("book-open")}Words you'll see</h2></header><div class="body"><dl class="gloss">${GLOSSARY.map(([t, d]) => `<div class="gloss-item"><dt>${esc(t)}</dt><dd>${esc(d)}</dd></div>`).join("")}</dl></div></div>`;
    ctx.stops.push(wireFlow($("[data-flow-root]")));
    $("[data-tour-again]").addEventListener("click", () => startTour());
  },
};

/* ---------- router ---------- */
function routeOf(path) {
  const p = path.replace(/\/+$/, "") || "/app";
  const m = p.match(/^\/app\/calls\/(.+)$/);
  if (m) return ["call", decodeURIComponent(m[1]), "calls"];
  const name = p === "/app" ? "overview" : p.replace(/^\/app\//, "");
  return views[name] && name !== "call" ? [name, null, name] : ["notfound", null, null];
}
function setCrumbs(parts) {
  $("[data-crumbs]").innerHTML = parts.map(([t, href], i) => (i < parts.length - 1 ? `<a href="${href}" data-nav>${esc(t)}</a>${icon("chevron-right")}` : `<b>${esc(t)}</b>`)).join("");
}
function showError(err) {
  if (err.name === "AbortError" || (err instanceof ApiError && err.status === 401)) return;
  content.innerHTML = errorState(err);
  $("[data-retry]")?.addEventListener("click", render);
}

async function render() {
  const [name, arg, nav] = routeOf(location.pathname);
  $$("[data-route]").forEach((a) => (a.dataset.route === nav ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  closeDrawer();
  ctx.timers.splice(0).forEach(clearInterval);
  ctx.stops.splice(0).forEach((f) => f());
  if (name === "notfound") {
    setCrumbs([["Not found"]]);
    content.innerHTML = `<div class="panel">${empty("search", "That page doesn't exist", "Check the address, or go back to the overview.", `<a class="btn btn-primary" href="/app" data-nav>Go to overview</a>`)}</div>`;
    return;
  }
  const v = views[name];
  document.title = `${v.title} · ShadowCall`;
  if (name !== "call") setCrumbs([[v.title]]);
  if (name !== "calls" || !$("[data-calls-body]")) content.innerHTML = skeletonPage(v.title);
  content.setAttribute("aria-busy", "true");
  try {
    await v.render(arg);
    addExplainer(name === "call" ? "call" : name);
  } catch (e) { showError(e); } finally { content.setAttribute("aria-busy", "false"); }
}
/** Every page gets a dismissible "What am I looking at?" box under its header. */
function addExplainer(page) {
  if (!$("[data-explain]")) {
    const head = content.querySelector(".ph");
    const html = explainer(page);
    if (head) head.insertAdjacentHTML("afterend", html); else content.insertAdjacentHTML("afterbegin", html);
  }
  wireExplainer(page);
}
function go(href) {
  if (href === location.pathname + location.search) return;
  history.pushState({}, "", href);
  render().then(() => { window.scrollTo(0, 0); content.focus({ preventScroll: true }); });
}

document.addEventListener("click", async (e) => {
  const a = e.target.closest("a[data-nav]");
  if (a && !e.metaKey && !e.ctrlKey && !e.shiftKey && a.origin === location.origin) { e.preventDefault(); go(a.pathname + a.search); return; }
  const run = e.target.closest("[data-run]");
  if (run) {
    const kind = run.dataset.run;
    const what = { train: "Collect examples", eval: "Run the fair test", live: "Send live calls" }[kind];
    if (!(await liveGuard(what))) return;
    const body = kind === "live" ? { n: 20, seed: Math.floor(Math.random() * 1000) } : { n: 120, seed: 21 };
    await busy(run, `${what}…`, async () => {
      try {
        const r = await api(`/api/${kind}`, { method: "POST", body });
        toast(`${what}: done`, kind === "train" ? `${r.trained_calls} practice calls answered and marked.` : kind === "live" ? `${r.calls} calls answered.` : "The gate re-checked all 4 jobs.");
        refreshCounts();
        await render();
      } catch (err) { toast(`${what} failed`, err.message, "bad"); }
    });
  }
});
window.addEventListener("popstate", render);
$("[data-tour-start]")?.addEventListener("click", () => { closeDrawer(); startTour(); });

/* drawer (mobile) */
const shell = $("[data-shell]"), menuBtn = $("[data-menu]");
function closeDrawer() { shell.classList.remove("open"); menuBtn.setAttribute("aria-expanded", "false"); }
menuBtn.addEventListener("click", () => { const o = shell.classList.toggle("open"); menuBtn.setAttribute("aria-expanded", String(o)); if (o) $(".nav a").focus(); });
$("[data-scrim]").addEventListener("click", closeDrawer);

/* keyboard: g + letter to jump, / to search */
let gPending = 0;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "/") { const q = $("[data-q]"); if (q) { e.preventDefault(); q.focus(); } else { e.preventDefault(); go("/app/calls"); setTimeout(() => $("[data-q]")?.focus(), 300); } return; }
  if (e.key === "g") { gPending = Date.now(); return; }
  if (Date.now() - gPending < 1200) {
    const to = { h: "/app/guide", o: "/app", t: "/app/try", c: "/app/calls", d: "/app/disagreements", f: "/app/corrections", g: "/app/gate", p: "/app/policy", e: "/app/evaluation", s: "/app/settings" }[e.key];
    gPending = 0;
    if (to) { e.preventDefault(); go(to); }
  }
});

$("[data-logout]").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* signing out anyway */ }
  location.href = "/login";
});

async function loadPills() {
  try {
    const s = await api("/api/settings");
    ctx.settings = s;
    const mp = $("[data-mode-pill]");
    mp.hidden = false;
    mp.className = `pill ${s.mode === "live" ? "live" : "mock"}`;
    mp.innerHTML = `<i></i>${s.mode === "live" ? "Live" : "Mock"}<span class="long">${s.mode === "live" ? " · Mubit" : " · simulated"}</span>`;
    const pp = $("[data-policy-pill]");
    pp.hidden = false;
    pp.innerHTML = `${icon("scroll-text", "icon")}<span>Policy <b class="mono" style="color:var(--fg);font-weight:500">${esc(s.policy)}</b></span>`;
  } catch { /* the page itself will show errors */ }
}

async function boot() {
  try {
    const me = await api("/api/auth/me");
    ctx.me = me;
    if (me.auth && !me.user) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
    setCsrf(me.csrf);
    const u = me.user;
    $("[data-user-name]").textContent = u ? (u.name || u.email.split("@")[0]) : "Local mode";
    $("[data-user-email]").textContent = u ? (u.demo ? "Demo account" : u.email) : "Sign-in is off";
    $("[data-avatar]").textContent = u ? (u.name || u.email).trim()[0].toUpperCase() : "L";
    if (!me.auth) $("[data-logout]").hidden = true;
  } catch (e) { showError(e); return; }
  await loadPills();
  refreshCounts();
  await render();
  if (!tourSeen() && !matchMedia("(max-width: 760px)").matches) setTimeout(startTour, 600);
}
boot();
