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
  errors, demands deeper investigation, refuses to wave through weak reasoning.

You run the show and stay neutral: you frame prompts, judge when the argument
is exhausted, relay questions to the user, and write the final plan.

## How it works

```
   you (orchestrator) — neutral: frames prompts, judges convergence, writes the plan
        │
   run_round.py — launches the round's agents in parallel, read-only
        │
   ┌────┴─────────────────┐
   │ LEAD                  │            JUDGE(S)
   │ owns the answer       │  ◄──────   "here is where you are wrong,
   │ defends / revises  ───┼────────►    and here is what you must investigate"
   └───────────────────────┘
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
   the judges' *critiques*; it never sees their independent round-1 answers.
   This preserves independence and keeps token cost down.
5. **You stay neutral.** You decide when arguments are exhausted and you write
   the final synthesis; you do not take a side in the argument itself.

## Brainstorm directory layout

```
brainstorms/<slug>/
├── brainstorm.md     # human-readable overview: topic, roles, status, summary
├── state.json        # machine state: round, agents + roles + session ids
├── objections.json   # machine-readable judge objections and closure evidence
├── topic.md          # the framed problem given to agents in round 1
├── sessions/
│   ├── <lead-name>/
│   │   ├── round-1.md   # round 1 = the lead's independent answer
│   │   └── round-3.md   # lead turns = revisions answering the judges
│   └── <judge-name>/
│       ├── round-1.md   # round 1 = the judge's independent study
│       └── round-2.md   # judge turns = critiques of the lead's answer
├── questions.md      # questions agents raised + the user's answers
├── log.md            # orchestration log: each CLI call, timing, cost, status
├── .raw/             # raw CLI output + prompts + configs (debug; script-written)
└── final-plan.md     # ← THE DELIVERABLE
```

Write `final-plan.md`, `brainstorm.md`, etc. in the **user's language**.

## The turn structure

After the independent round 1, judge turns and lead turns alternate:

| round | turn  | who runs    | what they read                         |
|-------|-------|-------------|-----------------------------------------|
| 1     | study | all agents  | the project only                       |
| 2     | judge | all judges  | the lead's round-1 answer              |
| 3     | lead  | lead only   | all judges' round-2 critiques          |
| 4     | judge | all judges  | the lead's round-3 answer              |
| 5     | lead  | lead only   | all judges' round-4 critiques          |
| 6     | judge | all judges  | the lead's round-5 answer              |

The loop ends early the moment every judge reports no further objections. The
cap (`max_rounds`, default 6) only bounds a brainstorm that will not converge.

## Workflow

Tell the user what is happening between phases — a round takes minutes.

### Phase 0 — Setup

1. **Settle the topic.** A brainstorm needs one concrete question, decision, or
   problem scoped to the project. If the user already stated it, confirm your
   understanding in one sentence; otherwise ask. A sharp topic is the single
   biggest lever on quality.

2. **Assign roles.** Default: two agents — `claude` as the **lead**, `codex` as
   a **judge**. The user may swap them, or add more judges. There is exactly
   one lead and one or more judges.

   Judging presets:
   - `cheap` (default): one judge. Lowest cost; lower confidence when a strong
     lead faces a single weaker judge.
   - `balanced`: two heterogeneous judges, preferably different model families.
     Higher cost; reduces single-judge/model-family bias.
   - `high-confidence`: `balanced` plus a mandatory fresh judge when the
     objection ledger shows an unearned flip.

   Cost tip to offer if the user is cost-sensitive: judges can be set to a
   cheaper/faster model.

3. **Preflight the CLIs:**
   ```bash
   python3 <skill-dir>/scripts/run_round.py --check
   ```
   If a CLI is missing or unauthenticated, stop and tell the user how to fix it
   (`codex` needs `codex login`; `claude` needs a normal Claude Code login).
   This includes a tiny paid Claude probe because Claude Code has no free
   headless auth-status command. Use `--no-probe-claude` only when the user
   explicitly wants a free install/version check. Suggest they run the fix as
   `! <command>` in the prompt.

4. **Create the brainstorm.** Invent a short kebab-case `slug`. Create
   `brainstorms/<slug>/` with a `sessions/<agent>/` subdir per agent and a
   `.raw/` subdir. Write `topic.md` (the framed problem — thorough; this is the
   agents' brief), `state.json`, `objections.json`, and seed `brainstorm.md` and
   `log.md`.

`state.json` shape:
```json
{
  "slug": "cache-redis-vs-lru",
  "topic_summary": "one-line summary",
  "status": "round-1",
  "round": 1,
  "max_rounds": 6,
  "judging_preset": "cheap",
  "agents": [
    {"name": "claude", "cli": "claude", "role": "lead",  "model": null, "session_id": null},
    {"name": "codex",  "cli": "codex",  "role": "judge", "model": null, "session_id": null}
  ]
}
```

`objections.json` starts as:
```json
{
  "version": 1,
  "objections": []
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
   answer **verbatim**, plus any new user answers. Write to
   `.raw/round-N-<judge>.prompt.md`. *(Round 2 = first presentation, always full
   paste. From round 4 you may opt into a verbatim **delta** paste instead — see
   "delta paste" in `prompt-templates.md` and the experimental gate below.)*
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
1. Build a lead-response prompt: paste **all** judges' latest critiques
   verbatim, labelled by judge, plus the current `objections.json` contents and
   any new user answers. *(Round 3 = first presentation, always full paste. From
   round 5 you may opt into a verbatim **delta** paste — see "delta paste" in
   `prompt-templates.md` and the gate below.)*
2. Write the round config listing **the lead only**, `session_id` set. Run it.
3. Persist as above.
4. Update `objections.json` with the lead's per-id responses. A response to
   each open id must be `conceded` or `rebutted` and cite evidence or the
   `## New investigation done this round` section.
5. Handle Phase 2 questions if any.

**Experimental: delta paste (context optimization, off by default).** On long
brainstorms the full re-paste of the counterpart's answer/critiques every round
grows context quadratically. From round 4 (judge) / 5 (lead) you may paste only
the **verbatim** changed sections plus the full `STATUS` line, relying on the
agent's resumed session for the unchanged remainder (mechanics in
`prompt-templates.md`). This is a **correctness-for-cost trade** — if the model
has dropped an unchanged section from its session memory, a delta leaves a gap.
Two hard rules: always save the *full* answer/critique to
`sessions/<agent>/round-N.md`, and gate the rollout behind an **A/B check** — run
the same topic once full-paste and once delta, and revert to full paste if
critique sharpness drops or rounds-to-converge rises. Default to full paste.

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
    {"name": "codex", "cli": "codex", "model": null,
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
     "exit_code": 0, "duration_seconds": 240.3, "timed_out": false,
     "cost_usd": null, "tokens": {"input": 9000, "output": 1200, "total": 10200},
     "attempts": [{"ok": true, "duration_seconds": 240.3, "error": null}],
     "error": null}
  ],
  "git_guard": {"available": true, "mutated_tree": false}
}
```
Use `verdict` to write the session file; carry `session_id` into the next
round; record timing/cost in `log.md`. For cost, log `cost_usd` when present
(claude) and fall back to `tokens.total` when it is null (codex reports no
dollar cost) — that keeps the log symmetric across agents. If `ok` is false,
read `error`, `attempts`, and the matching
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
