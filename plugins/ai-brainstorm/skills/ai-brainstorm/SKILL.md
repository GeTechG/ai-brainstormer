---
name: ai-brainstorm
description: >-
  Orchestrate a cost-efficient AI brainstorm where one lead model produces an
  answer and one or more judge models adversarially review it. Every model first
  investigates the current project independently; then the judges challenge the
  lead's answer round by round — naming errors, demanding deeper investigation —
  while the lead defends or revises, until no arguments remain. Produces one
  consolidated, battle-tested plan. Use this whenever the user wants several AI
  models to debate, brainstorm, cross-check, stress-test, peer-review, or reach
  consensus on a design, architecture, or technical decision — e.g. "run a
  brainstorm", "have another model review and challenge this", "get Claude and
  Codex to argue this out", "stress-test this approach with a second model",
  "get a second opinion and reconcile it". Trigger even if the user does not say
  the word "brainstorm" but clearly wants multiple models to independently
  analyze something and then reconcile it into a plan.
---

# AI Brainstorm

You are the **orchestrator** of a structured review between AI agents. The
agents are real CLI sessions (`claude`, `codex`) launched inside the user's
project, so each has the full project context, skills, and MCP servers — as if
the user opened that CLI themselves.

The brainstorm is asymmetric, which keeps it both rigorous and cheap:

- **One lead.** It owns the answer. It investigates, proposes, then defends or
  revises under challenge.
- **One or more judges.** Each adversarially reviews the lead's answer — finds
  errors, demands deeper investigation, refuses to wave through weak reasoning —
  **and proposes its own solution** so the lead sees a real alternative, not just
  a list of complaints.

You run the show and stay neutral: you frame prompts, judge when the argument
is exhausted, relay questions to the user, and write the final plan.

## Two modes

Pick the mode from the **shape of the question**, not by preference:

- **`adversarial_review`** (default) — use when the task is to **check or harden
  one concrete answer**: an architecture, a code change, a specific plan. The
  asymmetric lead/judge flow described in this file is strictly better here —
  machine-checkable convergence via `objections.json`, anti-capitulation controls
  (`suspect_closure`, fresh-judge), and a cheap one-directional information flow.
- **`symmetric_deliberation`** (opt-in) — use when the task is an **open "where
  should we take the project" question**: equal positions, opposing views meant
  to collide, a conclusion *derived from the clash* rather than averaged. There
  is no lead and no judge — every agent is an equal **participant**.

The mode lives in `state.json` (`"mode"`). When unsure which fits, ask the user:
"harden one specific answer" → `adversarial_review`; "explore a direction from
clashing views" → `symmetric_deliberation`.

**Why symmetry needs special design (and is not the default).** Naive symmetry
degrades into "average toward agreement", which produces a blander answer, not a
truer one. `symmetric_deliberation` avoids this by **decoupling the stop
criterion from agreement**: the deliberation ends when every decision-critical
claim is *resolved with evidence*, not when participants agree. The conclusion
may be `consensus`, `synthesis`, or recorded `dissent` — disagreement is
preserved, never erased. Three machine-enforced controls encode the no-averaging
rule (see "Symmetric deliberation" below).

Everything that follows describes `adversarial_review` unless a section is marked
for `symmetric_deliberation`.

## How it works

```
   you (orchestrator) — neutral: frames prompts, judges convergence, writes the plan
        │
   run_round.py — launches the round's agents in parallel, read-only
        │
   ┌────┴─────────────────┐
   │ LEAD                  │            JUDGE(S)
   │ owns the answer       │  ◄──────   "here is where you are wrong, here is
   │ defends / revises  ───┼────────►    what to investigate, and here is what
   └───────────────────────┘            I would do instead"
```

Why this is cheaper than an all-versus-all debate:

- On a **lead turn** only one model runs, not every agent — roughly halving the
  judge calls compared with running everyone every round.
- Judges never see each other, so no judge's context carries another's work.
- Judges can be set to a cheaper/faster model (the `model` field per agent).

Each agent keeps **one CLI session for the whole brainstorm**. Round 1 is a
fresh session; later rounds *resume* it, so an agent still remembers its own
prior reasoning. You inject only what the flow says it should see this turn.

### Invariants — do not break these

These are what make the brainstorm trustworthy.

1. **Only you write curated files inside `brainstorms/`.** Agents are instructed
   not to write there: `codex` is OS-sandboxed read-only, while `claude` relies
   on disabled editing tools plus prompt instructions (`Bash` stays enabled, so
   this is not an OS guarantee). Every curated file is written by you.
2. **Agents must not read `brainstorms/`,** and must stay inside the project
   directory. Each agent's prompt enforces this. It keeps round 1 genuinely
   independent and stops agents from discovering the orchestration machinery.
3. **Agents must not modify the project.** `codex` runs in an OS-level read-only
   sandbox — it physically cannot write. The `claude` CLI has no such sandbox: it
   runs with its file-editing tools (`Write`/`Edit`/`MultiEdit`/`NotebookEdit`)
   disabled, but `Bash` stays enabled for read-only investigation — so claude's
   read-only status is enforced **by instruction, not by sandbox**. Run
   brainstorms on a **clean git working tree** so any stray change is
   recoverable. Verdicts are captured from output — agents never need to write a file.
4. **Information flow is one-directional and minimal.** Judges see the lead's
   answer; they never see each other, nor each other's critiques. The lead sees
   the judges' *critiques, including the constructive `## Your proposed solution`
   each judge writes in its critique turn*; it never sees their verbatim
   independent round-1 answers. The proposal is re-articulated by the judge in
   the critique turn — so the lead gets the judge's own view of the problem
   without the round-1 file leaking. This preserves independence (the lead must
   still reason, not copy) and keeps token cost down.
5. **You stay neutral.** You decide when arguments are exhausted and you write
   the final synthesis; you do not take a side in the argument itself.

## Brainstorm directory layout

```
brainstorms/<slug>/
├── brainstorm.md     # human-readable overview: topic, roles, status, summary
├── state.json        # machine state: mode, round, agents + roles + session ids
├── objections.json   # adversarial_review: judge objections and closure evidence
├── deliberation.json # symmetric_deliberation: options + claims + positions ledger
├── topic.md          # the framed problem given to agents in round 1
├── sessions/
│   ├── <lead-name>/
│   │   ├── round-1.md   # round 1 = the lead's independent answer
│   │   ├── round-3.md   # lead turns = reconstructed full answer
│   │   └── round-3.delta.md # optional changed sections emitted by the agent
│   └── <judge-name>/
│       ├── round-1.md   # round 1 = the judge's independent study
│       └── round-2.md   # judge turns = critiques of the lead's answer
├── questions.md      # questions agents raised + the user's answers
├── log.md            # orchestration log: each CLI call, timing, cost, status
├── .raw/             # raw CLI output + prompts + configs (debug; script-written)
└── final-plan.md     # ← THE DELIVERABLE
```

**Language policy.** All agent-to-agent communication is in **English** — every
prompt you send to an agent and every verdict, critique, and ledger they return.
The session files under `sessions/` and `.raw/` therefore hold English. Only your
*direct* interaction with the user follows the user's language: you relay agents'
questions to the user in the user's language, and you write the user-facing
curated files — `final-plan.md`, `brainstorm.md`, and the chat summaries — in the
user's language. You are the translation boundary; translate user answers into
English before feeding them into the next round's prompts.

## The turn structure

After the independent round 1, judge turns and lead turns alternate:

| round | turn  | who runs    | what they read                         |
|-------|-------|-------------|-----------------------------------------|
| 1     | study | all agents  | the project only                       |
| 2     | judge | all judges  | the lead's round-1 answer              |
| 3     | lead  | lead only   | all judges' round-2 critiques + proposals |
| 4     | judge | all judges  | the lead's round-3 answer              |
| 5     | lead  | lead only   | all judges' round-4 critiques + proposals |
| 6     | judge | all judges  | the lead's round-5 answer              |

The loop ends early when the objection ledger has no open or suspect entries.
The cap (`max_rounds`, default 6) only bounds a brainstorm that will not
converge.

## Workflow

Tell the user what is happening between phases — a round takes minutes.

### Phase 0 — Setup

1. **Settle the topic.** A brainstorm needs one concrete question, decision, or
   problem scoped to the project. If the user already stated it, confirm your
   understanding in one sentence; otherwise ask. A sharp topic is the single
   biggest lever on quality.

2. **Pick the mode** (see "Two modes"). Default `adversarial_review` for hardening
   one concrete answer; `symmetric_deliberation` for an open "where to take the
   project" question. If `symmetric_deliberation`, the rest of Phase 0 still
   applies but every agent gets `role: "participant"` (no lead/judge), and you
   follow the "Symmetric deliberation" section for the loop and finalize.

3. **Assign roles** (`adversarial_review`). Default: two agents — `claude` as the
   **lead**, `codex` as a **judge**. The user may swap them, or add more judges.
   There is exactly one lead and one or more judges.

   Judging presets:
   - `cheap` (default): one judge. Lowest cost; lower confidence when a strong
     lead faces a single weaker judge.
   - `balanced`: two heterogeneous judges, preferably different model families.
     Higher cost; reduces single-judge/model-family bias.
   - `high-confidence`: `balanced` plus a mandatory fresh judge when the
     objection ledger shows an unearned flip.

   Cost tip to offer if the user is cost-sensitive: judges can be set to a
   cheaper/faster model.

   **Models (per agent).** Each agent's `model` field selects its model; `null`
   (the default) means that CLI's own default model — whatever the user has
   configured, with no override. If the user names a model in their request, set
   the relevant agent's `model` to that string verbatim — the runner forwards it
   as `claude --model <m>` / `codex -m <m>`. The user may set it globally ("run
   the brainstorm on opus"), per role ("lead on opus, judge on gpt-5-codex"), or
   per named agent. Use each CLI's own model names/aliases: for a `claude` agent,
   an alias like `opus`/`sonnet`/`haiku` or a full id like `claude-opus-4-8`; for
   a `codex` agent, a Codex model name like `gpt-5-codex`. Leave `model: null`
   for any agent the user did not single out — do not invent a model the user did
   not ask for.

   **Reasoning effort (per agent).** Each agent's `effort` field selects its
   reasoning-effort level; `null` (the default) means the CLI's own default
   effort — no override. If the user asks for more/less thinking (globally, per
   role, or per agent), set the relevant agent's `effort` and the runner forwards
   it as `claude --effort <e>` / `codex -c model_reasoning_effort=<e>`. Use each
   CLI's own levels: for a `claude` agent, `low|medium|high|xhigh|max`; for a
   `codex` agent, `minimal|low|medium|high`.

   **Do not set `effort` unless the user explicitly asked for it.** When unset,
   each CLI runs at its own configured default, which is usually the
   best-balanced choice — e.g. `codex` at its default (`medium`) tends to give
   the best results, and lowering it can hurt the review. Only override when the
   user asks ("think harder", "high effort", "quick low-effort pass"); otherwise
   leave `effort: null` for every agent.

4. **Preflight the CLIs:**
   ```bash
   python3 <skill-dir>/scripts/run_round.py --check
   ```
   If a CLI is missing or unauthenticated, stop and tell the user how to fix it
   (`codex` needs `codex login`; `claude` needs a normal Claude Code login).
   This includes a tiny paid Claude probe because Claude Code has no free
   headless auth-status command. Use `--no-probe-claude` only when the user
   explicitly wants a free install/version check. Suggest they run the fix as
   `! <command>` in the prompt.

5. **Create the brainstorm.** Invent a short kebab-case `slug`. Create
   `brainstorms/<slug>/` with a `sessions/<agent>/` subdir per agent and a
   `.raw/` subdir. Write `topic.md` (the framed problem — thorough; this is the
   agents' brief), `state.json`, the mode's ledger file (`objections.json` for
   `adversarial_review`, `deliberation.json` for `symmetric_deliberation`), and
   seed `brainstorm.md` and `log.md`.

`state.json` shape (`adversarial_review`):
```json
{
  "slug": "cache-redis-vs-lru",
  "topic_summary": "one-line summary",
  "mode": "adversarial_review",
  "status": "round-1",
  "round": 1,
  "max_rounds": 6,
  "judging_preset": "cheap",
  "delta_mode": "section-id",
  "last_seen_round": {},
  "agents": [
    {"name": "claude", "cli": "claude", "role": "lead",  "model": null, "effort": null, "session_id": null},
    {"name": "codex",  "cli": "codex",  "role": "judge", "model": null, "effort": null, "session_id": null}
  ]
}
```

For `symmetric_deliberation`, set `"mode": "symmetric_deliberation"`, give every
agent `"role": "participant"`, and keep `last_seen_round` as an agent↔agent
matrix (each participant sees each other). Default to **two** participants (two
opposing models); 3+ is a deliberate, more expensive choice (payload grows
≈O(N²)).

`objections.json` (`adversarial_review`) starts as:
```json
{
  "version": 1,
  "objections": []
}
```

`deliberation.json` (`symmetric_deliberation`) starts as:
```json
{
  "version": 1,
  "options": [],
  "claims": [],
  "positions": []
}
```

### Phase 1 — Round 1: independent study

Every agent — lead and judges alike — investigates the project independently
and produces a full answer. The lead's answer becomes "the answer under
review". Each judge's answer is its private grounding: a judge that has truly
thought the problem through gives a far sharper critique than one reacting cold.

1. For each agent, build a round-1 prompt from `references/prompt-templates.md`
   (read that file now if you have not). Round 1 uses the **same** prompt for
   every agent — no per-role version; roles take effect only from round 2. Write
   each to `.raw/round-1-<agent>.prompt.md`.
2. Write the round config (see "Calling run_round.py") listing **all** agents,
   `session_id: null`. Run it.
3. For each agent: write the verdict verbatim to `sessions/<agent>/round-1.md`
   (small header: name, role, round, duration, cost); append to `log.md`; save
   the `session_id` into `state.json`.
4. If an agent failed, show the user its `error` and the `.raw/` log; decide
   together whether to retry that agent or abort.
5. If any verdict has a `## QUESTIONS FOR USER` section, handle Phase 2.

### Phase 2 — Relay questions to the user (whenever they arise)

Agents are headless and cannot ask interactively, so they route questions
through you. Whenever a round surfaces questions:

1. Collect them from all agents, de-duplicate, and ask the user (use
   `AskUserQuestion` for crisp choices, or just ask in chat).
2. Record every question and answer in `questions.md`.
3. The answers are authoritative and go into the **next** round's prompt for
   the agents that need them (the `{USER_ANSWERS_SECTION}` of the templates).

### Phase 3 — Review loop (alternating judge / lead turns)

Repeat until convergence or the round cap.

**Judge turn** (rounds 2, 4, 6, …):
1. For each judge, build a judge-critique prompt: paste the lead's latest
   answer sections **verbatim**, plus any new user answers. Round 2 is the
   first presentation, so paste the full lead answer. From round 4, paste only
   the changed section-id blocks that the lead emitted, plus the full
   `## LEAD STATUS`; use `last_seen_round[judge][lead]` to know the base. Write
   to `.raw/round-N-<judge>.prompt.md`. If the judge looks confused, an id is
   missing, or the lead delta is thin, set the prompt to full paste and update
   `last_seen_round` after the run.
2. Write the round config listing **the judges only**, each with its
   `session_id` set (resumes the session). Run it.
3. Persist: write `sessions/<judge>/round-N.md`, update `log.md`, `state.json`.
4. Handle Phase 2 questions if any.
5. **Update `objections.json`.** Judges must emit a machine-readable objection
   ledger block. Merge entries by `id`, preserving history:
   - New or still-open objections have `status: "open"`.
   - Closed objections have `status: "closed"` and `closed_by` naming the
     concrete new evidence that resolved them.
   - If a judge closes or drops an objection without new evidence from the lead,
     mark it `suspect_closure: true`.

6. **Check convergence from the ledger, not prose.** Convergence means every
   ledger entry is `closed` and no entry has `suspect_closure: true`. The prose
   `## JUDGE STATUS` is only a human-readable summary. A judge that simply goes
   quiet without engaging existing ids is **not** convergence: run one more
   judge turn telling it to close or restate each id concretely.

   **Fresh-judge control (anti-capitulation).** In `high-confidence`, and in
   any preset where `suspect_closure: true` remains, run a **fresh judge**: a
   brand-new session (`session_id: null`) that never took part in the debate,
   given the same round-1 prompt then the lead's final answer as a one-shot
   judge turn. If it raises a substantive objection, reopen the loop.

**Lead turn** (rounds 3, 5, …):
1. Build a lead-response prompt: paste every judge's latest critique sections
   verbatim, labelled by judge, plus the current `objections.json` contents and
   any new user answers. Round 3 is the first presentation, so paste every
   critique in full. From round 5, paste only each judge's changed section-id
   blocks plus the full `## JUDGE STATUS`; use `last_seen_round[lead][judge]`
   to know the base. Fall back to full paste on any doubt.
2. Write the round config listing **the lead only**, `session_id` set. Run it.
3. Persist as above.
4. Update `objections.json` with the lead's per-id responses. A response to
   each open id must be `conceded` or `rebutted` and cite evidence or the
   `## New investigation done this round` section.
5. Handle Phase 2 questions if any.

**Section-id delta mode (default after first presentation).** Full re-paste of
answers and critiques grows context quadratically. After an agent has seen the
counterpart's full answer once, send only verbatim changed section-id blocks and
the full status line. The agent, not the orchestrator, marks which sections
changed, so fidelity comes from the author of the change instead of a manual
diff. Hard rules: always save the reconstructed full answer/critique to
`sessions/<agent>/round-N.md`; save the emitted delta separately when present;
track `last_seen_round` per agent pair; send full content before finalization
and to any fresh judge; fall back to full paste when an answer is thin, ids are
missing, references are incoherent, or the model seems to have lost context.

**Handling deadlock.** If a judge and the lead circle the same point with no
new arguments, do not let the loop spin. That point is either:
- *objectively decidable with more evidence* — instruct the relevant agent, in
  its next prompt, to go get that specific evidence; or
- *a genuine judgment call, or needs a fact only the user has* — extract it and
  ask the user (Phase 2), then feed the answer back as authoritative.

At the round cap, stop and go to Phase 4 from the lead's latest answer; the
final plan must fairly document any objection left standing.

### Phase 4 — Finalize

1. Write `final-plan.md` — the deliverable: the lead's final, judge-hardened
   answer, written up as an actionable plan, in the user's language:

   ```
   # Brainstorm: <topic>

   ## Summary
   The conclusion in a short paragraph.

   ## The plan
   Concrete, ordered, specific steps.

   ## Rationale
   Why this approach — the arguments that survived judge review.

   ## Risks and mitigations

   ## Open points   (include only if a judge objection remained unresolved)
   Each unresolved point stated fairly, with your neutral recommendation.

   ## How it was hardened
   One line per round: what the judges challenged and what changed.
   ```

2. Update `brainstorm.md` (status: finalized, round-by-round summary) and
   `state.json` (`status: "finalized"`).

3. Present the plan to the user in chat and point to `final-plan.md`.

## Symmetric deliberation (mode `symmetric_deliberation`)

This mode reuses Phase 0 (setup), Phase 1 (round 1), and Phase 2 (questions)
unchanged — **round 1 is identical**: the same independent-study prompt for
everyone, no roles. Only the review loop and finalize differ. Use the *Symmetric
deliberation turn* and *Symmetric final stance* templates.

**What changes vs the default flow:**

- **No lead/judge.** Every agent is a `participant`. Each round, run **all**
  participants in parallel (resumed sessions) — there is no cheap one-model lead
  turn. At N=2 this is ~1.7× the calls of asymmetric review; expected.
- **The orchestrator injects counterparts' positions.** Agents still never read
  `brainstorms/`. Round 2 pastes each participant's full round-1 position to the
  others; from round 3 use section-id deltas (same delta discipline as default,
  tracked in the `last_seen_round` matrix). At N=2 each sees exactly one
  counterpart; at N≥3 paste each of the other N-1 under its own labelled block.
- **`deliberation.json` replaces `objections.json`.** After each round, merge the
  participants' emitted ledger blocks into `deliberation.json` by id, preserving
  history across `options`, `claims`, and `positions`.

**Convergence — decoupled from agreement (this is the anti-averaging core).**
Stop the loop when **all three** hold; agreement is NOT one of them:

1. Every `decision_critical` claim is `accepted` or `rejected` **with**
   `resolution_evidence`; none left `open`.
2. Every position change carries `change_evidence`; otherwise the entry is
   `suspect_flip: true` and the loop is not converged.
3. (At finalize) every participant emitted a `FINAL STANCE` with a
   `recommended_option` and the claim ids that led there.

Three machine-checkable controls, all derivable from ledger fields, encode the
user's no-averaging requirement:

- **Stop by claim-resolution, not by agreement** (criterion 1) — removes the
  pressure to capitulate just to finish.
- **Resolution authority on a claim:** a claim with `challenged_by: [X]` may move
  to `accepted` only when **X explicitly drops** its challenge with
  `resolution_evidence`; otherwise it stays `unresolved`. Without this, "accepted"
  degrades back into prose-agreement.
- **`unearned_synthesis` flag:** a new synthesis option is admissible only if it
  cites concrete `accepted` claims from **both** sides (`cross_side_claims`). A
  synthesis with no cross-side claim ids is flagged and cannot become the final
  recommendation. This is "merging ideas is fine; collapsing to the middle for
  agreement is not", encoded.

**Anti-capitulation.** `suspect_flip` is the direct analogue of `suspect_closure`:
a position change with no new evidence (or no dropped challenge) → flag → run one
more symmetric turn, or a fresh audit.

**Finalize (Phase 4 variant).**
1. **Fresh audit over the artifact, not `brainstorms/`.** Run a fresh agent
   (`session_id: null`, never in the debate) given the round-1 prompt, then the
   consolidated stance artifact + `deliberation.json`, asked to audit the
   `decision_critical` claims as an outside auditor (mechanics identical to the
   fresh-judge control). This is asymmetry of the *final check* only, not of
   answer-ownership during the debate; the "never read `brainstorms/`" invariant
   holds because the orchestrator pastes the artifact in.
2. Write `final-plan.md`. The result may be `consensus`, `synthesis`, or
   `dissent` (majority/minority + unresolved claims). **Preserve disagreement** —
   an `## Open points` section must state any standing dissent and unresolved
   claims fairly, never average them away.
3. Update `brainstorm.md` and `state.json` (`status: "finalized"`).

## Calling run_round.py

The script runs one round: it launches the listed agents in parallel,
read-only, with a timeout, and returns structured JSON. It writes only into
`.raw/`. It does not care about roles — roles live entirely in the prompts you
write; the script just runs whatever agents the config lists.

**Config** — write it to `.raw/round-N.config.json`:
```json
{
  "project_dir": "/absolute/path/to/project",
  "raw_dir": "/absolute/path/to/brainstorms/<slug>/.raw",
  "timeout_seconds": 1800,
  "round": 2,
  "agents": [
    {"name": "codex", "cli": "codex", "model": null, "effort": null,
     "session_id": "<id from round 1>",
     "prompt_file": "/abs/.raw/round-2-codex.prompt.md"}
  ]
}
```
- List **all agents** for round 1; **only the judges** for a judge turn;
  **only the lead** for a lead turn.
- `session_id`: `null` for round 1 (fresh session); the id returned by the
  previous round for every later turn (resumes that session).
- `model`: `null` uses the CLI's default model.
- `effort`: `null` uses the CLI's default reasoning effort; else a per-CLI level
  (claude: `low|medium|high|xhigh|max`; codex: `minimal|low|medium|high`).
- `timeout_seconds`: per-agent wall-clock cap; 1800 (30 min) is a safe default.
  Agents in a round run in parallel, so wall time is the slowest agent.

**Run it:**
```bash
python3 <skill-dir>/scripts/run_round.py --config /abs/.raw/round-N.config.json
```

**Result** (stdout JSON):
```json
{
  "ok": true,
  "round": 2,
  "results": [
    {"name": "codex", "cli": "codex", "ok": true,
     "session_id": "...", "verdict": "<full answer text>",
     "prompt_chars": 9000, "prompt_hash": "sha256:...",
     "exit_code": 0, "duration_seconds": 240.3, "timed_out": false,
     "cost_usd": null, "tokens": {"input": 9000, "output": 1200, "total": 10200},
     "attempts": [{"ok": true, "duration_seconds": 240.3, "error": null}],
     "error": null}
  ],
  "git_guard": {"available": true, "mutated_tree": false}
}
```
Use `verdict` to write the session file; carry `session_id` into the next
round; record timing/cost plus `prompt_chars`/`prompt_hash` in `log.md`. Use
the prompt telemetry to verify that section-id delta rounds are actually
shrinking prompts in A/B comparisons. For cost, log `cost_usd` when present
(claude) and log token categories separately when it is null (codex reports no
dollar cost) — do not present `tokens.total` as money. If `ok` is false, read
`error`, `attempts`, `ledger_validation_error` when present, and the matching
`.raw/round-N-<agent>.attemptK.*.log` files to diagnose. Always inspect
`git_guard`: if `mutated_tree` is true, stop the brainstorm and tell the user
the project tree changed during the round. The guard uses `git status`, so it
does not detect gitignored files; for high-safety runs, use a disposable
worktree or copy.

## Notes and edge cases

- **A brainstorm needs a lead and at least one judge.** With no judge there is
  nothing to stress-test the answer.
- **An agent fails mid-brainstorm.** Show the error and `.raw/` log. You can
  retry just that agent with a single-agent config carrying its `session_id`.
  If a judge cannot be recovered, you can finish with the remaining judges; if
  the lead cannot be recovered, the brainstorm cannot continue — report that.
- **A judge raises no objections in round 2.** Genuine quick agreement is fine,
  but verify the round-2 critique actually engaged the answer. If it was a thin
  rubber-stamp, run one more judge turn asking for a real review.
- **The lead caves under pressure.** Watch for the lead conceding points
  without evidence just to end the argument — that ships a worse answer. If you
  see it, the next lead prompt should tell it to only concede what the evidence
  actually forces.
- **Resuming an interrupted brainstorm.** `state.json` holds the round number,
  every role, and every session id, so you can pick up where it stopped.
- **Cost.** Each round is real CLI usage. Judge turns run every judge; lead
  turns run one model. Mention this if the user is cost-sensitive, and offer to
  set judges to a cheaper model.
- **Token accounting.** Claude and Codex usage schemas differ. Treat Codex cache
  fields as provisional until measured against a real `turn.completed.usage`
  sample; do not claim exact dollar cost for Codex.
- **Prompt caching.** Do not claim precise per-block cache attribution. Repeated
  static prompt text increases observed context and may create cache-write
  tokens, but treat the effect as a measured hypothesis using `prompt_chars`,
  `prompt_hash`, and raw usage.
