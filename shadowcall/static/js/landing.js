import { api, pct, pence } from "/static/js/api.js";
import { flowHtml, wireFlow } from "/static/js/guide.js";

const $ = (s, r = document) => r.querySelector(s);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

async function load() {
  try {
    const [m, me] = await Promise.all([api("/api/public/metrics"), api("/api/auth/me")]);
    $('[data-m="calls"]').textContent = m.calls.toLocaleString("en-GB");
    $('[data-m="switched"]').textContent = `${m.switched} of ${m.subtasks}`;
    $('[data-m="pass"]').textContent = pct(m.frontier_pass_rate);
    $('[data-m="pence"]').textContent = m.pence_frontier ? `${pence(m.pence_frontier)} → ${m.pence_served == null ? "–" : pence(m.pence_served)}` : "–";
    const mock = m.mode !== "live";
    $("[data-live-dot]").classList.toggle("warn", mock);
    $("[data-live-label]").textContent = mock
      ? "Live from this server · mock mode: both models are simulated, so these numbers test the pipeline and are not results"
      : "Live from this server · real calls through Mubit";
    if (me && me.user) $("[data-auth-slot]").innerHTML = '<a class="btn btn-primary" href="/app">Open console</a>';
  } catch {
    $("[data-live-label]").textContent = "Live numbers are unavailable right now.";
    $("[data-live-dot]").classList.add("warn");
  }
}

/** The hero call: bubbles arrive, both models work through the 4 jobs, the checker marks them, the gate switches. */
function heroDemo() {
  const demo = $("[data-demo]");
  if (!demo) return;
  const bubs = [...demo.querySelectorAll("[data-b]")];
  const typing = $("[data-typing]", demo), check = $("[data-check]", demo), sw = $("[data-demo-switch]", demo), timer = $("[data-demo-timer]", demo);
  const lbl = $(".gate-mini .lbl", demo);
  const final = () => {
    bubs.forEach((b) => b.classList.add("show"));
    demo.classList.add("s-work", "s-check");
    check.textContent = "both right · saved as a learning example";
    lbl.textContent = "After the fair test:";
    sw.classList.add("small");
  };
  if (reduce) { final(); timer.textContent = "00:14"; return; }
  let secs = 0, timeouts = [];
  setInterval(() => { if (!document.hidden) timer.textContent = `00:${String(++secs % 60).padStart(2, "0")}`; }, 1000);
  const at = (ms, fn) => timeouts.push(setTimeout(fn, ms));
  const run = () => {
    timeouts.forEach(clearTimeout); timeouts = [];
    secs = 0;
    bubs.forEach((b) => b.classList.remove("show"));
    demo.classList.remove("s-work", "s-check");
    sw.classList.remove("small");
    check.textContent = "listening…";
    lbl.textContent = "Understand the caller";
    at(400, () => bubs[0].classList.add("show"));
    at(1200, () => typing.classList.add("show"));
    at(2300, () => { typing.classList.remove("show"); bubs[1].classList.add("show"); });
    at(3300, () => bubs[2].classList.add("show"));
    at(3900, () => { demo.classList.add("s-work"); check.textContent = "both models are answering…"; });
    at(5600, () => { demo.classList.add("s-check"); check.textContent = "both right · saved as a learning example"; });
    at(7200, () => { lbl.textContent = "After the fair test:"; sw.classList.add("small"); });
    at(11000, run);
  };
  run();
}

function flow() {
  const root = $("[data-flow-root]");
  if (!root) return;
  root.innerHTML = flowHtml();
  wireFlow(root, { autoplay: !reduce });
}

function reveal() {
  if (reduce || !("IntersectionObserver" in window)) return;
  const els = document.querySelectorAll(".section .l-wrap > *, .cta h2");
  const obs = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); obs.unobserve(e.target); } }), { rootMargin: "0px 0px -8% 0px" });
  els.forEach((el) => { if (el.getBoundingClientRect().top > innerHeight) { el.classList.add("reveal"); obs.observe(el); } });
}

load();
heroDemo();
flow();
reveal();
