// Plain-English layer for first-time users: names, tooltips, page explainers, the six-step flow and the tour.
import { esc, icon } from "/static/js/api.js";

export const NAMES = {
  extract: ["Understand the caller", "Who is calling, what they want, and when"],
  policy_check: ["Check the rules", "Is the booking allowed? Any fee or deposit?"],
  form_fill: ["Fill the booking form", "Turn the call into the practice's form"],
  summary: ["Write the summary", "A short note for the staff"],
};
export const stName = (k) => `<span class="st-name"><b>${esc((NAMES[k] || [k])[0])}</b><code>${esc(k)}</code></span>`;
export const plain = (k) => (NAMES[k] || [k])[0];

/** A small "?" that explains the thing next to it, on hover, focus or tap. */
export const tip = (text, where = "") => `<button type="button" class="tip ${where}" data-tip="${esc(text)}" aria-label="${esc(text)}">?</button>`;

export const TIPS = {
  cost: "What one call costs in AI fees, in pence. \"From\" is the cost if the big model did every job. Lower is better.",
  switched: "Each call has 4 jobs. This counts how many jobs the small model now answers for real, after passing the test.",
  agree: "On real calls, how often both models got the same mark from the rule checker.",
  pass: "On test calls neither model trained on: how often the small model's answer matched the practice's rules exactly. The big model's score is underneath, for comparison.",
  kept: "Answers the checker confirmed as correct, saved as learning examples. Mubit starts training after 25 for a job, so the app warns before that.",
  meter: "Score on test calls the models never trained on, marked by the rule checker. Orange is the big model, purple the small one.",
  rail: "Learning examples saved for this job. One square per example; Mubit starts training at 25.",
  switch: "Who answers this job on real calls right now. It only moves to Small after passing the test.",
  heldout: "A test call: kept apart and never used for learning, so the score is fair.",
  red: "Emergencies such as severe swelling or bleeding. Missing even one blocks the switch.",
  latency: "How long the model took to answer, in milliseconds. Under about 800 ms feels instant on a phone.",
  n: "How many test calls this score is based on.",
  servedSmall: "How many jobs on this call the small model answered for real.",
  keptCol: "How many answers from this call were saved as learning examples.",
};

export const EXPLAIN = {
  guide: ["How ShadowCall works, in six steps", "Click any step to see what happens there. The same six steps run on every call.", "Judges look for a mistake turning into a better model. Steps 4 to 6 are where that happens."],
  overview: ["This is the scoreboard", "It shows how much each call costs, how many of the 4 jobs the small model has taken over, and the newest calls as they arrive.", "Lower cost with no drop in correctness is the whole point. Every number has a ? if you want the detail."],
  calls: ["Every call the system has seen", "Each row is one phone call. The pass columns count how many of its 4 jobs each model got right, marked by the rule checker. Open a row to see both answers side by side.", "This is the evidence trail. Nothing is hidden: you can check any score yourself."],
  call: ["One call, both models, side by side", "Left is what the caller heard (the big model). Right is what the small model would have said. Green ticks and red crosses come from the rule checker, not from another AI.", "Red lines show exactly which field was wrong, so you can see why a job is or isn't ready to switch."],
  disagreements: ["Calls where the two models disagreed", "Only one of them passed the rule checker. \"Small model right\" rows are the big model's own mistakes.", "These show the small model is checked against the rules, not just copying the big one."],
  corrections: ["Fixing the big model's mistakes", "When the big model gets a job wrong, it is shown the checker's note and answers again. Fixed answers become learning examples. Ones it can't fix wait here for a person.", "This is the learning loop: a mistake becomes a correct example, so the next model is better."],
  gate: ["Who answers each job right now", "Each of the 4 jobs has its own switch. It moves to the small model only after the small model scores as well as the big one on test calls, with no missed emergencies.", "Safety first: you can roll any job back to the big model in one click."],
  policy: ["The practice's booking rules", "The rule checker marks every answer against these rules. Change them (v1 to v2) and every switched job goes back to the big model until it passes again.", "Shows the system copes when the business changes, instead of quietly going wrong."],
  evaluation: ["The fair test", "The same test calls go through four versions: the big model, the small model untrained, and the small model trained on every answer or only on checked answers.", "If \"checked answers\" beats \"every answer\", the checker is what makes the difference."],
  settings: ["How this server is set up", "Mode, models, prices and the gate's thresholds. Keys only show Set or Not set; their values never reach your browser.", "Mock mode means simulated models: good for a demo, not for quoting results."],
  try: ["Try a call yourself", "Pick a call card and press Run. Both models answer, the checker marks them, and you see the result in seconds. You can edit what the caller says.", "The quickest way to see the whole loop on one call."],
};

export function explainer(page) {
  const e = EXPLAIN[page];
  if (!e) return "";
  const hidden = localStorage.getItem(`sc_explain_${page}`) === "hide";
  return `<section class="explain" data-explain="${page}" ${hidden ? "hidden" : ""} aria-label="What am I looking at?">
    ${icon("lightbulb")}<div><h2>${esc(e[0])}</h2><p>${esc(e[1])}</p><p class="why"><b>Why it matters:</b> ${esc(e[2])}</p></div>
    <button class="icon-btn" type="button" data-explain-hide aria-label="Hide this explainer">${icon("x")}</button></section>`;
}
export function wireExplainer(page) {
  const box = document.querySelector("[data-explain]");
  const open = document.querySelector("[data-explain-open]");
  if (!open) return;
  open.hidden = !box || !box.hidden;
  if (!box) return;
  box.querySelector("[data-explain-hide]").addEventListener("click", () => {
    box.hidden = true; localStorage.setItem(`sc_explain_${page}`, "hide"); open.hidden = false; open.focus();
  });
  open.onclick = () => { box.hidden = false; localStorage.removeItem(`sc_explain_${page}`); open.hidden = true; box.scrollIntoView({ block: "nearest" }); };
}

export const FLOW = [
  ["phone-incoming", "Call comes in", "Caller", "", "A patient rings the dental practice. The voice agent turns their speech into text.", "\"Hiya, I'd like a check-up on Tuesday at half 10.\""],
  ["bot", "Big model answers", "Big model", "frontier", "The expensive, clever model answers straight away, like today. Until a job is switched, this is the only answer the caller hears.", "intent: book · treatment: check-up · time: 10:30"],
  ["split", "Small model shadows", "Small model", "small", "A cheap model does the same 4 jobs quietly in the background. Nobody hears it. We only keep its answers to compare.", "intent: book · treatment: check-up · time: 10:30"],
  ["shield-check", "Checker marks both", "Rule checker", "", "A checker built from the practice's own booking rules marks each answer right or wrong. It is plain code, not another AI, so it can't be talked round.", "big model ✓ right · small model ✓ right"],
  ["wrench", "Mistakes get corrected", "Big model + a person", "frontier", "If the big model was wrong, it sees the checker's note and tries again. Correct answers become learning examples. If it still can't fix it, a person approves the fix.", "checker's note → asked again → right → saved as a learning example"],
  ["badge-check", "The gate decides", "Promotion gate", "small", "When the small model scores as well as the big one on test calls it never trained on, with no missed emergencies, that job switches to the small model. Rules change? It switches back.", "as good on 20+ test calls, no missed emergencies → switched to Small"],
];

export function flowHtml() {
  return `<div class="flow" role="tablist" aria-label="How a call is handled">${FLOW.map((f, i) => `<button type="button" class="flow-step ${i === 0 ? "on" : ""}" role="tab" aria-selected="${i === 0}" data-step="${i}" ${f[3] ? `data-tone="${f[3]}"` : ""}>
      <span class="num"><span class="dot">${icon(f[0])}</span><span class="wire"></span></span>
      <span class="actor">${i + 1} · ${esc(f[2])}</span><h3>${esc(f[1])}</h3></button>`).join("")}</div>
    <div class="flow-detail" data-flow-detail aria-live="polite"></div>`;
}
export function wireFlow(root, { autoplay = true } = {}) {
  const steps = [...root.querySelectorAll("[data-step]")];
  const detail = root.querySelector("[data-flow-detail]");
  if (!steps.length) return () => {};
  let cur = 0, timer = null;
  const show = (i) => {
    cur = i;
    steps.forEach((s, j) => { s.classList.toggle("on", j === i); s.classList.toggle("done", j < i); s.setAttribute("aria-selected", String(j === i)); });
    const f = FLOW[i];
    detail.innerHTML = `<b>${i + 1}. ${esc(f[1])}.</b> ${esc(f[4])}<div class="ex">${esc(f[5])}</div>`;
  };
  steps.forEach((s, i) => s.addEventListener("click", () => { stop(); show(i); }));
  const stop = () => { clearInterval(timer); timer = null; };
  show(0);
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (autoplay && !reduce) timer = setInterval(() => { if (!document.body.contains(detail)) return stop(); show((cur + 1) % FLOW.length); }, 3600);
  return stop;
}

export const GLOSSARY = [
  ["Big model (frontier)", "The expensive, clever AI the practice uses today. It answers the caller."],
  ["Small model", "A cheap, fast open AI. It learns by watching, and only takes over a job once it has proved itself."],
  ["Job (sub-task)", "Each call is split into 4 jobs: understand the caller, check the rules, fill the form, write the summary."],
  ["Rule checker (verifier)", "Plain code built from the practice's booking rules. It marks every answer right or wrong."],
  ["Test calls (held-out)", "Calls kept apart and never used for learning, so the score is fair."],
  ["Learning example (kept)", "An answer the checker confirmed. These teach the small model. Mubit trains after 25 per job."],
  ["Correction", "The big model sees what it got wrong and answers again. Fixed answers become learning examples."],
  ["Promotion gate", "The rule that decides when a job switches to the small model, and when it goes back."],
  ["Red flag", "An emergency the agent must never miss. One miss blocks a switch."],
  ["Mock mode", "Both models are simulated so the demo runs offline. Its numbers test the pipeline; they are not results."],
];

/* ---------- guided tour ---------- */
const TOUR = [
  [null, "Welcome to ShadowCall", "A dental practice's phone agent runs on an expensive \"big\" AI model. ShadowCall lets a cheap \"small\" model learn from it quietly, and lets it take over a job only once a rule checker proves it is just as good. This takes about a minute."],
  ['[data-route="guide"]', "Start here if you're new", "Six steps, one picture: a call comes in, both models answer, the checker marks them, mistakes get fixed, and the gate decides who answers next time."],
  ['[data-route="overview"]', "The scoreboard", "Cost per call, how many jobs the small model has taken over, and new calls as they arrive. Hover any ? for a plain-English explanation."],
  ['[data-route="calls"]', "Every call, fully open", "Open any call to see both models' answers side by side, with the checker's ticks and crosses."],
  ['[data-route="corrections"]', "Where mistakes become lessons", "When the big model is wrong, it gets the checker's note and tries again. Anything it can't fix waits here for a person."],
  ['[data-route="gate"]', "Who answers each job", "Each job has a switch. It only moves to the small model after a fair test, and you can roll it back in one click."],
  ['[data-route="try"]', "Try it yourself", "Pick a call card, press Run, and watch the whole loop happen on one call."],
  ['[data-explain-open], [data-explain]', "Lost? Ask the page", "Every page has a \"What am I looking at?\" box. Hide it once you've got it; bring it back from the top bar."],
];

export function startTour() {
  const host = document.querySelector("[data-tour]");
  let i = 0;
  const finish = () => { host.hidden = true; host.innerHTML = ""; localStorage.setItem("sc_tour_v2", "done"); document.removeEventListener("keydown", onKey); document.querySelector("[data-tour-start]")?.focus(); };
  const onKey = (e) => { if (e.key === "Escape") finish(); if (e.key === "ArrowRight") step(i + 1); if (e.key === "ArrowLeft") step(i - 1); };
  document.addEventListener("keydown", onKey);
  function step(n) {
    if (n < 0) return;
    if (n >= TOUR.length) return finish();
    i = n;
    const [sel, title, body] = TOUR[i];
    const el = sel ? [...document.querySelectorAll(sel)].find((x) => x.offsetParent !== null && x.getBoundingClientRect().width > 0) : null;
    host.hidden = false;
    host.innerHTML = `<div class="tour-blocker"></div>${el ? `<div class="tour-spot"></div>` : ""}
      <div class="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-t"><div class="step">Step ${i + 1} of ${TOUR.length}</div><h2 id="tour-t">${esc(title)}</h2><p>${esc(body)}</p>
      <footer><span class="dots">${TOUR.map((_, j) => `<i class="${j === i ? "on" : ""}"></i>`).join("")}</span><span class="sp"></span>
      <button class="btn btn-sm btn-ghost" type="button" data-t="skip">${i === 0 ? "Skip" : "Close"}</button>${i > 0 ? `<button class="btn btn-sm" type="button" data-t="back">Back</button>` : ""}
      <button class="btn btn-sm btn-primary" type="button" data-t="next">${i === TOUR.length - 1 ? "Done" : i === 0 ? "Show me" : "Next"}</button></footer></div>`;
    const card = host.querySelector(".tour-card");
    if (el) {
      const r = el.getBoundingClientRect(), pad = 4, spot = host.querySelector(".tour-spot");
      Object.assign(spot.style, { top: `${r.top - pad}px`, left: `${r.left - pad}px`, width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px` });
      const right = r.right + 16 + 340 < innerWidth;
      card.style.left = `${right ? r.right + 16 : Math.max(12, Math.min(r.left, innerWidth - 352))}px`;
      card.style.top = `${right ? Math.max(12, Math.min(r.top - 8, innerHeight - 240)) : Math.min(r.bottom + 12, innerHeight - 240)}px`;
    } else {
      card.style.left = `${Math.max(12, innerWidth / 2 - 170)}px`;
      card.style.top = `${Math.max(12, innerHeight / 2 - 140)}px`;
    }
    host.querySelector('[data-t="next"]').addEventListener("click", () => step(i + 1));
    host.querySelector('[data-t="skip"]').addEventListener("click", finish);
    host.querySelector('[data-t="back"]')?.addEventListener("click", () => step(i - 1));
    host.querySelector('[data-t="next"]').focus();
  }
  step(0);
}
export const tourSeen = () => localStorage.getItem("sc_tour_v2") === "done";
