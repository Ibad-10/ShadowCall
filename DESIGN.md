# DESIGN.md: ShadowCall design system

ShadowCall is its own brand. This system takes the *patterns* of the best operator consoles (dense data-first tables, hairline structure, one accent, keyboard-first, quiet chrome) and describes them in our own terms. It copies no assets, marks, copy or exact palettes from any product.

Inputs:
- The `ui-ux-pro-max` design-system search (style *Data-Dense Dashboard*, density 8, motion 3, variance 4; the palettes "Developer Tool / IDE" and "API Developer Portal"; the font pairing "Developer Mono": JetBrains Mono with IBM Plex Sans).
- The `impeccable` craft floor (Operate mode for the console, Persuade mode for the landing page).

## 1. The idea: "night shift"
The product watches calls while the practice sleeps. The world is a **control room at night**:
- near-black ink with a faint blue cast;
- hairline rules instead of boxes;
- figures set in a tabular mono;
- one bright **signal** colour (chartreuse) reserved for "go": primary actions, the current selection and "switched".

The two models get their own fixed hues everywhere:
- **frontier** is warm copper, because it's expensive and lights the way;
- **small/shadow** is cool periwinkle, because it's quiet and follows.

You learn the pair once and can read every chart, badge and diff from then on.

**Why dark:** the use scene is an expo hall, a projector and late-night operators (PRODUCT.md). It isn't dark because "dev tools are dark". Every text pair below meets WCAG AA on its surface.

## 2. Tokens (`static/css/tokens.css`)

### Colour
| Token | Value | Use |
|---|---|---|
| `--ink-0` | `#090B0E` | page canvas |
| `--ink-1` | `#0D1014` | sidebar, top bar (second neutral layer) |
| `--ink-2` | `#12161B` | panels, tables |
| `--ink-3` | `#191E25` | hover rows, raised controls |
| `--ink-4` | `#222831` | pressed, selected rows |
| `--line` | `#1F252D` | hairlines (1px) |
| `--line-2` | `#2C343E` | control borders, dividers that must read |
| `--fg` | `#E7EBF0` | primary text (16.6:1 on ink-2) |
| `--fg-2` | `#A7B0BC` | secondary text (8.4:1) |
| `--fg-3` | `#7D8896` | tertiary, captions, axis labels (5.0:1) |
| `--signal` | `#C6F16D` | primary action, focus ring, current nav, "switched" |
| `--on-signal` | `#11160A` | text on signal |
| `--frontier` | `#F0A562` | frontier-model data |
| `--small` | `#9AA6FF` | small/shadow-model data |
| `--ok` | `#53D18E` | passed, verified |
| `--warn` | `#E9C750` | needs attention, mock mode |
| `--bad` | `#FF6E6E` | failed, rolled back, destructive |
| `--info` | `#79C2FF` | neutral notices |

Each semantic colour has a `-bg` (12% alpha on the ink) and a `-line` (35% alpha) for badges and notices. Never put semantic colour on large areas.

### Type
- **Sans:** IBM Plex Sans (variable, self-hosted, OFL) for UI, headings and prose.
- **Mono:** JetBrains Mono (variable, self-hosted, OFL) only for **data**: IDs, JSON, money, percentages, timestamps and request IDs. It is never used for decoration.
- `font-variant-numeric: tabular-nums` is set on every number column.
- **Console scale:** a fixed rem scale with a 1.2 ratio.

  | Size | Use |
  |---|---|
  | 12 | caption |
  | 13 | table and dense UI |
  | 14 | body |
  | 16 | section title |
  | 20 | page title |
  | 28 | KPI figure |

- **Landing scale:**
  - display `clamp(2.6rem, 5.4vw, 4.6rem)`, weight 600, tracking -0.03em, `text-wrap: balance`;
  - lead 18–20px;
  - body measure 62ch.
- **Weights:** 400 for body, 500 for labels and nav, 600 for titles and figures.

### Space, radius and depth
- **Space:** a 4px base, with the scale 4 · 8 · 12 · 16 · 20 · 24 · 32 · 48 · 64 · 96. Dense tables use 8×12 cells.
- **Radius:** 6px for controls, 10px for panels, 999px for badges and dots only.
- **Depth:** structure comes from hairlines, not shadows. Only floating layers (menus, toasts, the detail drawer) get `0 12px 32px -8px rgb(0 0 0 / .6), 0 2px 6px rgb(0 0 0 / .4)`.

### Motion
| Token | Value |
|---|---|
| `--ease-out` | `cubic-bezier(.16, 1, .3, 1)` (exponential out) |
| `--t-fast` | 120ms (hover, press) |
| `--t-base` | 180ms (state change) |
| `--t-slow` | 320ms (drawer, route fade) |

- Motion only ever conveys state: a route crossfade, row hover, a skeleton shimmer, a live dot pulsing while the mode is live, and toasts.
- The landing page has **one authored moment**. The hero "trace" shows a call flowing to both models, the verifier ticking, and the small lane lighting up.
- `prefers-reduced-motion` turns all motion off, and the final state renders immediately.

## 3. Layout
- **Console shell:**
  - a 240px sidebar (collapses to a 64px icon rail at ≤1100px and an off-canvas drawer at ≤760px);
  - a 52px top bar with breadcrumb, mode pill, policy pill and user menu;
  - content max-width 1480px, padding 24px (16px on mobile).
- **Grid:** 12 columns with a 16px gutter. The KPI strip is **one bordered row split by hairlines**, not a grid of cards.
- **Pages** follow the same rhythm:
  1. page title, a one-line explanation and the actions on the right;
  2. a filter bar;
  3. the primary table or chart;
  4. secondary panels.
- **Tables** scroll horizontally inside their own panel on small screens. The page itself never scrolls sideways.

## 4. Components
Every interactive component has default, hover, focus-visible (a 2px signal ring with a 2px offset), active, disabled and loading states.

| Component | Spec |
|---|---|
| Button | Heights 32 (sm) and 36 (md). **Primary:** signal fill, on-signal text. **Secondary:** ink-3 fill with a line-2 border. **Ghost:** transparent. **Danger:** bad text with a bad-line border; it fills on hover. **Loading:** spinner icon plus a verb in -ing ("Running…"), and the button is disabled. |
| Badge | 20px tall, 12px text with 500 weight, a coloured dot and a label. Variants: `switched` (signal), `shadow` (small), `rolled_back` (bad), `passed`/`failed`, `mock` (warn). Colour is never the only carrier: there is always a text label. |
| Lane chip | A dot plus "Frontier" or "Small" in the lane colour. It is used in tables, diffs and chart legends. |
| KPI cell | Label (12, fg-3), figure (28 mono 600), and a delta or context line (12, fg-2). It sits inside the strip with hairline dividers. |
| Table | Sticky header (12, fg-3, uppercase is **not** used), 13px rows 40px tall, a hover ink-3 background, a row link covering the whole row, numbers right-aligned in mono. Empty state: a sentence that teaches, plus the action that fills it. |
| Panel | ink-2 background, a line border, 10px radius, header 44px (title 14/600 plus actions). Panels never nest. |
| JSON diff | Two columns (Frontier / Small) with the truth below. Fields that differ from the truth are underlined in bad with a "≠ truth" tag; correct fields are plain. |
| Gate meter | A horizontal bar: small accuracy against frontier accuracy, with tick marks for the margin and the min-held-out count ("38/20 held-out"). |
| Progress to 25 | A 25-segment rail. Kept examples fill in signal, and a warn tick marks the cap. It reads as "kept 14 / 25 · training starts at 25". |
| Toast | Bottom right, ink-3, with a 1px line. It auto-dismisses after 5s and is announced through `aria-live="polite"`. |
| Notice | An inline bar for mock mode, live mode or errors. It has an icon, one sentence and an optional action. There is no coloured side stripe. |
| Skeleton | ink-3 blocks with a 1.2s shimmer (none under reduced motion), sized to the real content so nothing shifts. |
| Forms | Visible labels above the field. Inputs are 40px tall with an ink-1 background and a line-2 border; focus shows a signal ring. Errors sit under the field with an icon and the recovery step. `autocomplete` is set correctly, and there is a password reveal toggle. |

**Icons:** Lucide (ISC), vendored as an SVG sprite, with a 1.75 stroke at 16/18px. No emoji or Unicode stand-ins.

## 5. States
- **Loading:** skeletons within 100ms. Buttons show their own spinner. Pages never blank.
- **Empty:** teaches the next action, e.g. "No calls yet. Run a mock training batch to see the pipeline work." with a [Run 60 mock calls] button.
- **Error:** an inline notice saying what failed and how to recover, e.g. "Couldn't load calls (500). Retry". It never shows a raw stack.
- **Mock mode:** a persistent warn pill in the top bar: "Mock: simulated models, not results".
- **Auth expired:** an API 401 redirects to `/login?next=…`.

## 6. Accessibility
- **Contrast:** AA everywhere; see the colour table.
- **Keyboard:**
  - a skip link;
  - every action is reachable by keyboard;
  - `g` then a letter jumps between pages (`g o` overview, `g c` calls and so on);
  - `/` focuses search.
- **Landmarks:** `nav`, `main`, `header`, with `aria-current="page"` on the nav item for the current page.
- **Charts:** each has a text table alternative (`<table class="sr-only">` or a visible data table).
- **Pointer targets:** at least 32px in the console and 44px on touch breakpoints.

## 7. Browser surfaces
- Selection is signal at 30% alpha.
- The caret is signal.
- Scrollbars are thin, ink-4 on transparent.
- `color-scheme: dark`.
- Underline offset is 3px.
- The favicon is our own SVG mark: two offset circles, solid copper and outlined periwinkle, the "shadow".

## 8. Pages
| Route | Mode | Purpose |
|---|---|---|
| `/` | Persuade | Hero with the live trace, a metrics strip from `/api/public/metrics`, how it works in 4 steps, the safety section, a CTA |
| `/login`, `/signup` | Operate | A single focused form beside the brand panel |
| `/app` | Operate | Overview: KPI strip, sub-task gate table, kept-to-25 rails, recent gate events |
| `/app/calls` (+ `/app/calls/:id`) | Operate | Searchable list; detail with transcript, 4 sub-tasks frontier vs small vs truth, and verdicts |
| `/app/disagreements` | Operate | Who was right, by verifier |
| `/app/corrections` | Operate | Status breakdown and the Fix queue with Approve |
| `/app/gate` | Operate | Sub-tasks with badges, gate evidence, rollback / return to shadow |
| `/app/policy` | Operate | v1/v2 diff, active policy, Fast refresh |
| `/app/evaluation` | Operate | Held-out ablation table plus a grouped bar chart (A frontier, B base, C raw, D verified) |
| `/app/settings` | Operate | Mode, models, endpoints, keys present yes/no (values never shown), gate and learning settings |

## 9. Banned here
- Gradient text.
- Glass used as decoration.
- Eyebrow labels above headings.
- Identical icon-card grids.
- Coloured side-stripe borders.
- Hero-metric templates.
- Mono as costume.
- Emoji icons.
- Modals for non-destructive tasks. Approve and rollback act inline, with an undo toast where possible.

## 10. Version 2: references and blend (24 Oct 2026)

We studied five public sites for ideas only. No logos, brand names or copy were taken. The raw captures are in `design-refs/` next to this project.

| Took from | What | Where it shows |
|---|---|---|
| Linear-style ops tools | Ink surfaces, see-through white hairlines (`--line` .07, `--line-2` .12, `--line-3` .2), tight heading tracking, quick 100–160 ms ease | Console chrome, panels, tables |
| ElevenLabs-style voice tools | Pill buttons and segmented controls (`--r-pill`), 0.5 px ring shadow (`--ring`), standard ease | Buttons, filters, badges, FAQ |
| Vapi-style voice demos | An animated example call: bubbles arrive, a typing dot, work lights up, a result lands | Landing hero, live call feed |

Brand colours stay: signal `#C6F16D`, big model copper `#F0A562`, small model periwinkle `#9AA6FF`.

### Motion tokens

| Token | Value | Use |
|---|---|---|
| `--ease-quick` | `cubic-bezier(.25,.46,.45,.94)` | Hover, focus, small state changes |
| `--ease-std` | `cubic-bezier(.4,0,.2,1)` | Colour and toggle changes |
| `--ease-out` | `cubic-bezier(.16,1,.3,1)` | Things arriving: feed rows, bubbles, the gate knob |
| `--t-fast` / `--t-base` / `--t-slow` / `--t-enter` | 100 / 160 / 400 / 520 ms | |

With `prefers-reduced-motion: reduce`, every duration is 0. The hero call and the six-step flow then show their final state and don't loop.

### New components (`static/css/console-guide.css`, `static/js/guide.js`)

- **Tooltip** (`.tip`): a small round "?" next to a metric or column. It opens on hover or keyboard focus. The text is also its `aria-label`.
- **Explainer** (`.explain`): a "What am I looking at?" box under each page header. It says what the page shows and why it matters. Hide it with ×; the top bar button brings it back. Remembered per page.
- **Tour** (`.tour-card`, `.tour-spot`): 8 steps over the sidebar. It starts on the first desktop visit and is restarted from "Take the 1-minute tour". Esc closes it; ← and → move.
- **Six-step flow** (`.flow`): call comes in → big model answers → small model shadows → checker marks both → mistakes corrected → gate decides. Click a step or let it play.
- **Live call feed** (`.feed`): the newest calls, checked every 4 s from `GET /api/feed?after=<cursor>`. New rows slide in. It can be paused.
- **Gate switch** (`.switch`): Big | Small, with a knob that slides when a job moves to the small model and turns red when rolled back.
- **Get-started checklist** (`.checklist`): three clicks for an empty console, with done and next states.

### Words

On screen we say "big model", "small model", "job", "rule checker", "test calls", "learning examples". The technical name sits beside it in mono where it helps (`extract`, `held-out`).
