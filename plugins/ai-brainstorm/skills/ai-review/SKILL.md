---
name: ai-review
description: >-
  Cross-model adversarial code review. A judge model — a *different* model from
  the one you are running (Claude → Codex by default, or the reverse) — reviews
  your code changes in a fresh, clean session, and you, the **respondent** who
  launched the skill, fix or rebut each finding round by round until the judge
  finds nothing left. The scope can be your uncommitted changes (default) or a
  whole PR / branch (everything a branch introduces vs its base). The judge is
  read-only and re-reviews the live repo each round in the *same resumed session*,
  so it remembers what it already flagged. Use this whenever the user wants a
  second model to review, check, audit, or sign off on their code changes or a
  pull request — e.g. "have Codex review my changes", "get another model to review
  this diff", "cross-check my edits with a different model", "review this PR /
  branch with another model", "run a code review on my uncommitted changes", "let
  a judge model inspect what I changed and loop until it's clean". Trigger even if
  the user does not say "review" but clearly wants an independent model to
  scrutinize their changes or branch and drive them to a clean state. There is
  also a **lite mode** — a fast, low-token, file-free pass meant to run right
  before a commit: no review directory is created, the judge runs immediately,
  returns a short findings list, you apply the fixes, and it loops once or twice
  until clean. Lite mode is **no weaker at finding problems** than the full
  review — it scrutinizes the same dimensions and flags the same issues at the
  same severities; what it strips is the ceremony (files, JSON ledger, PR scope),
  not the detection rigor. Trigger lite mode when the user wants a *quick /
  lightweight / pre-commit* check — e.g. "облегчённое ревью", "быстрое ревью перед коммитом",
  "quick review before I commit", "lite cross-model check", "погоняй судью по-быстрому".
---

# AI Review

You are the **respondent** in a cross-model code review. Unlike `ai-brainstorm`
(where you stay a neutral orchestrator and every agent is headless and
read-only), here **you are a participant**: you own the code under review, you
**fix** it, and you drive the loop. A **judge** — a separate CLI session of a
*different model* — adversarially reviews your uncommitted changes, returns
findings, and you fix or rebut them, round after round, until the judge reports
the change is clean.

```
   you (RESPONDENT) — live session that launched the skill
        │  own the change · fix or rebut findings · drive the loop · WRITE code
        │
   run_round.py — launches the judge, read-only, resumes its session
        │
   JUDGE — fresh clean session of a DIFFERENT model
        │  reviews the live `git diff` · emits a findings ledger · read-only
        └────────►  "here is what is wrong, by file:line, with evidence"
```

Why a different model judges: a second model from another family catches what
your own model's blind spots miss. The judge starts cold (clean session, no
memory of your reasoning) so it reviews the *code*, not your rationalizations.

**Two modes.** Default is the **full** review documented below — it writes a
`reviews/<slug>/` record, supports PR/branch scope, runs a JSON findings ledger,
and is built for a thorough, resumable, auditable sign-off. The **lite mode**
(see "Lite mode" near the end) is the opposite trade-off on *ceremony*, not on
*rigor*: zero curated files, a short non-JSON findings list, uncommitted changes
only, one cheap judge, capped at ~2 rounds — a fast, low-token polish to run
right before you commit. It reviews the **same dimensions** and surfaces the
**same problems at the same severities** as the full flow; the only things it
gives up are the on-disk record, the JSON ledger, and PR/branch scope. When the
user asks for a *quick / lightweight / pre-commit* check, use lite mode; when
they want an auditable record, a resumable run, or a PR/branch review, use the
full flow.

## Roles

- **Respondent** = **you**, the live agent running this skill. You may have the
  full prior context of how the change was made, or none — either way you must
  **investigate the change yourself** before defending it, exactly as the judge
  will. You are the only one who writes to the project.
- **Judge** = a headless CLI of a **different model**. Default: if you are Claude,
  the judge is **`codex`**; offer **`claude`** (a fresh, clean Claude session — a
  weaker, same-family check) as the alternative. The judge is **read-only**
  (`codex` by OS sandbox; `claude` with editing tools disabled) and reviews the
  real working tree.

## Invariants — do not break these

1. **Only you write to the project.** The judge is read-only and never edits,
   creates, or deletes files. `run_round.py`'s git-guard verifies the tree was
   not mutated *during a judge round*; between rounds, you (the respondent) are
   the one who changes files, and that is expected.
2. **The judge reviews the live repo, not a snapshot.** Each round the judge
   re-runs the scope's diff command itself in the project dir (`git diff HEAD`
   for uncommitted changes, `git diff <base>...HEAD` for a PR/branch), so it
   always sees your latest fixes — working-tree edits *or* new fix commits. You
   never paste the diff — you tell it the scope; it reads the code.
3. **The judge keeps one session for the whole review.** Round 1 is a fresh
   session; later rounds *resume* it (`session_id`), so the judge remembers the
   findings it already raised and can tell what you actually resolved.
4. **Findings are evidence-gated.** Every finding must cite `file:line` and a
   concrete reason. A finding without checkable evidence is dropped, not fixed.
5. **You may rebut, not only fix.** When a finding is wrong, you rebut it with
   evidence rather than damaging the code to silence the judge. Convergence
   requires the *judge* to accept your rebuttal — you do not get to close a
   finding unilaterally.

## What is reviewed (scope)

Confirm the scope in one sentence before starting. Three shapes:

- **Uncommitted changes (default):** `git status` + `git diff HEAD`, **including
  new untracked files**. Fixes are working-tree edits.
- **PR / branch:** everything the branch *introduces* vs its base — use the
  **three-dot merge-base diff** `git diff <base>...<branch>` (e.g.
  `git diff main...HEAD`), **not** two-dot, so a base that moved ahead does not
  add noise. The base defaults to the repo's main branch; ask if unclear. For a
  GitHub PR, check it out first (`gh pr checkout <number>`), then review
  `git diff <base>...HEAD`. **Fixes are new commits on the branch** (see Phase 3),
  so the judge's `base...HEAD` diff picks them up each round.
- **Explicit paths or a single commit:** `git diff HEAD -- <paths>`, or
  `git show <sha>` for one commit.

In every shape the judge raises findings on the *introduced* lines; anything
pre-existing it notices is marked `pre_existing: true` and does **not** block. The
exact scope (mode, base, branch/paths) is recorded in `state.json` so re-review
rounds and resume use the identical diff command.

## Review dimensions

The judge reviews comprehensively but **adapts** the applicable dimensions to the
project type. Default to **correctness**; do not let it drown the review in style
nits.

**Core (always on):**
1. **Correctness / logic** — bugs, off-by-one, null/undefined handling, wrong
   conditionals, dead paths, "does it do what it claims".
2. **Edge cases & error handling** — unhandled exceptions, silent failures,
   swallowed errors; concurrency/races for concurrent code.
3. **Security** — injection, hardcoded secrets, unsafe deserialization/crypto,
   missing input validation, data/PII exposure.
4. **Project-convention adherence** — existing patterns, structure, naming, and
   any rules in `CLAUDE.md`/`AGENTS.md`.
5. **Simplicity / reuse** — duplication, over-engineering, reinventing existing
   utilities.
6. **Tests** — new branches covered, tests assert real behavior, they pass.

**Also on by default (this configuration):**
7. **Architecture / design** — coupling, separation of concerns, integration
   with existing systems.
8. **Performance / efficiency** — bottlenecks, O(n²), leaks — *only* when it is a
   real problem, not speculative.
9. **Production readiness** — migrations, backward compatibility, rollback safety.
10. **Documentation / comments** — completeness; comments left stale by the change.

The exact dimension set is recorded in `state.json` (`dimensions`) so a run is
reproducible; the user may trim it at setup.

## Severity and the stop threshold

Three tiers, and the judge must **not** inflate them:

- 🔴 **blocker** — would break production or is a security hole.
- 🟡 **important** — a real bug, missing case, or convention violation worth fixing.
- ⚪ **nit** — style/preference; reported, capped (~5, then "+N similar"), **never
  blocks**.

**Stop threshold (this configuration): `blocker + important`.** The loop ends when
no `open` finding of severity `blocker` or `important` remains — every one is
either `resolved` (you fixed it) or `rebutted` *and accepted by the judge*. Nits
may remain open without blocking. After round 1, the judge must **not** raise new
nits on unchanged code (re-review suppression). A hard cap (`max_rounds`, default
4) bounds a review that will not converge.

## Review directory layout

```
reviews/<slug>/
├── review.md            # human-readable overview: scope, status, summary
├── state.json           # machine state: round, judge agent + session id, threshold, dimensions
├── scope.md             # the exact change under review (given to the judge each round)
├── findings.json        # the findings ledger across rounds — SOURCE OF TRUTH for convergence
├── rounds/
│   ├── round-1.judge.md       # judge's findings verbatim
│   ├── round-1.respondent.md  # your fixes/rebuttals log for that round
│   └── round-2.judge.md       # judge re-review verbatim
├── .raw/                # run_round.py raw output + prompts (debug; script-written)
└── review-summary.md    # ← THE DELIVERABLE
```

**Language policy.** All communication between you and the judge is in
**English** — every prompt you send and every findings list, ledger, and
question the judge returns. The `rounds/` and `.raw/` files therefore hold
English. Only your *direct* interaction with the user follows the user's
language: relay the judge's questions in the user's language, and write the
user-facing curated files — `review.md`, `review-summary.md`, and the chat
summaries — in the user's language. You are the translation boundary; translate
user answers into English before feeding them into the next judge prompt. This
directory is runtime output (gitignored) — temporary, for logging and resume.

## The turn structure

| round | who runs   | what happens                                            |
|-------|------------|---------------------------------------------------------|
| 1     | judge      | fresh session reviews the scope → findings ledger       |
| —     | respondent | you fix / rebut each finding, log it, update the tree   |
| 2     | judge      | *resumed* session re-reviews the live tree → updated ledger |
| —     | respondent | fix / rebut what remains                                |
| 3     | judge      | …                                                       |

The loop ends when the ledger has no `open` blocker/important finding, or at
`max_rounds`.

## Workflow

Tell the user what is happening between phases — a judge round takes minutes.

### Phase 0 — Setup

1. **Settle the scope.** Pick the shape (see "What is reviewed"): uncommitted
   changes (default), a PR/branch (resolve the base — default the repo's main
   branch — and `gh pr checkout` first for a GitHub PR), or explicit paths / a
   commit. Confirm it in one sentence. If the chosen scope is *empty* (no diff),
   say so and stop.
2. **Pick the judge.** Default `codex` (different family). Offer `claude` (fresh
   clean session) if the user prefers, or if `codex` is unavailable. The judge
   must be a different *session* than yours regardless; prefer a different *model*.
   **Judge model.** The `judge.model` field selects its model; `null` (the
   default) means that CLI's own default — whatever the user has configured, with
   no override. If the user names a model in their request ("review with codex on
   gpt-5-codex", "judge with haiku"), set `judge.model` to that string verbatim —
   the runner forwards it as `claude --model <m>` / `codex -m <m>`. Use the CLI's
   own model names/aliases (claude: `opus`/`sonnet`/`haiku` or a full id like
   `claude-haiku-4-5-20251001`; codex: a model name like `gpt-5-codex`). Leave
   `model: null` to use the default.
3. **Confirm dimensions and threshold** only if the user wants to deviate from the
   defaults above.
4. **Preflight the judge CLI:**
   ```bash
   python3 <skill-dir>/../ai-brainstorm/scripts/run_round.py --check
   ```
   (The runner is shared with the `ai-brainstorm` skill in this plugin.) If the
   judge CLI is missing or unauthenticated, stop and tell the user how to fix it
   (`codex` needs `codex login`; `claude` needs a normal login). Use
   `--no-probe-claude` if the judge is `codex` and you want to skip the tiny paid
   Claude probe.
5. **Create the review.** Invent a short kebab-case `slug`. Create
   `reviews/<slug>/` with `rounds/` and `.raw/` subdirs. Write `scope.md` (the
   exact change description handed to the judge), `state.json`, an empty
   `findings.json`, and seed `review.md`.

`state.json` shape:
```json
{
  "slug": "fix-auth-redirect",
  "scope_summary": "one-line summary of what is under review",
  "scope": {"mode": "uncommitted", "base": null, "branch": null, "paths": [],
            "diff_cmd": "git diff HEAD"},
  "status": "round-1",
  "round": 1,
  "max_rounds": 4,
  "stop_threshold": "important",
  "dimensions": ["correctness","edge-cases","security","conventions","simplicity",
                 "tests","architecture","performance","prod-readiness","docs"],
  "judge": {"name": "codex", "cli": "codex", "model": null, "session_id": null}
}
```

`findings.json` starts as:
```json
{ "version": 1, "findings": [] }
```

### Phase 1 — Investigate your own change first

Before the judge runs, **read the scope's diff yourself** (`scope.diff_cmd`, e.g.
`git diff HEAD` or `git diff <base>...HEAD`, plus `git status`). You must
understand the change well enough to fix and to rebut — whether or not you
authored it in this session. This is what lets you push back on a wrong finding
instead of blindly "fixing" it.

### Phase 2 — Judge round

1. Build the judge prompt from `references/review-prompts.md`:
   - **Round 1:** the *Judge round 1* template — full scope, dimensions, severity
     rules, and the findings-ledger schema.
   - **Round ≥ 2:** the *Judge re-review* template — short. "You reviewed this
     change before; I have addressed your findings. Re-run the scope's diff and
     re-review the **current** change; update the ledger: mark what is now
     resolved, keep what still stands, and consider my rebuttals." Do not
     re-explain the rules; the resumed session remembers them.
   Write the prompt to `.raw/round-N-judge.prompt.md`.
2. Write the round config (see "Calling run_round.py"): **one agent** (the judge),
   `session_id: null` for round 1, the saved id thereafter. Run it.
3. Persist: write the judge's verdict verbatim to `rounds/round-N.judge.md`
   (header: round, duration, cost/tokens); save the returned `session_id` into
   `state.json`; append to `review.md`.
4. **Update `findings.json`.** Merge the judge's emitted ledger by `id`,
   preserving history. A finding the judge confirms is resolved gets
   `status: "resolved"` with `resolved_by` naming the concrete change. A finding
   the judge accepts your rebuttal on gets `status: "rebutted"`. New issues get
   fresh ids and `status: "open"`.
5. **Inspect `git_guard`.** If `mutated_tree` is true, the judge wrote to the tree
   despite being read-only — stop and tell the user.

### Phase 3 — Respondent round (you fix or rebut)

For every `open` finding at or above the stop threshold (`blocker`, `important`;
nits are optional):

1. **Investigate** the cited `file:line` to confirm the finding is real.
2. Decide and act:
   - **Real** → **fix it.** Make the change, keep it minimal and in the project's
     style. Note what you changed. **In PR/branch scope, commit the fixes** (one
     or more fix commits on the branch) so the judge's `<base>...HEAD` diff
     reflects them next round; in uncommitted scope they are just working-tree
     edits. Do not commit unless the scope is a branch, or the user asked.
   - **Wrong** → **rebut it** with concrete evidence (file/line/command output)
     showing why it does not hold. Do **not** mangle the code to appease a bad
     finding — an unearned "fix" ships worse code.
   - **Genuine judgment call or needs a fact only the user has** → per this
     configuration, you rebut on evidence where you can; for a true judgment call,
     surface it to the user (see below) and record their decision as authoritative.
3. Write your per-finding actions to `rounds/round-N.respondent.md` and update
   each finding's response fields in `findings.json` (`response.action` =
   `fixed | rebutted | deferred`, with evidence).
4. If a finding needs a user decision, ask the user now (use `AskUserQuestion` for
   crisp choices), record it, and treat the answer as authoritative in the next
   judge prompt.

Then go back to **Phase 2** with the judge's resumed session.

### Phase 4 — Convergence and finalize

**Convergence** (check the ledger, not the prose): every finding of severity
`blocker`/`important` is `resolved`, or `rebutted` *and* the judge did not
re-raise it in its latest round. A judge that simply goes quiet is not
convergence — if open ids were neither re-raised nor acknowledged, run one more
judge round asking it to explicitly resolve or hold each open id. If a rebuttal
and a finding circle with no new evidence, that point is either decidable with
more evidence (tell the relevant side to go get it) or a judgment call (ask the
user). At `max_rounds`, stop and document anything still standing.

Then write **`review-summary.md`** — the deliverable, in the user's language:

```
# Cross-model review: <scope>

## Outcome
Clean / clean-with-open-nits / stopped at round cap — one line.

## What the judge caught and what changed
One line per resolved blocker/important finding: the issue and the fix.

## Rebuttals the judge accepted
Findings you pushed back on, with the evidence that settled them.

## Open points   (only if any blocker/important remained, or nits left open)
Each stated fairly, with your recommendation.

## Rounds
One line per round: what the judge raised, what you did.
```

Update `review.md` (status: finalized) and `state.json` (`status: "finalized"`).
Present the outcome to the user in chat and point to `review-summary.md`.

## Calling run_round.py

The review reuses the `ai-brainstorm` runner unchanged — it runs one agent
read-only, with a timeout, resumes its session, guards the tree, and returns
structured JSON. The judge is just a single agent in the config.

**Config** — write it to `.raw/round-N.config.json`:
```json
{
  "project_dir": "/absolute/path/to/project",
  "raw_dir": "/absolute/path/to/reviews/<slug>/.raw",
  "timeout_seconds": 1800,
  "round": 1,
  "agents": [
    {"name": "codex", "cli": "codex", "model": null,
     "session_id": null,
     "prompt_file": "/abs/.raw/round-1-judge.prompt.md"}
  ]
}
```
- Always exactly **one agent** (the judge).
- `session_id`: `null` for round 1 (fresh session); the id returned by the
  previous round for every re-review (resumes the judge's session).
- `model`: `null` uses the CLI's default model.

**Run it:**
```bash
python3 <skill-dir>/../ai-brainstorm/scripts/run_round.py --config /abs/.raw/round-N.config.json
```

**Result** (stdout JSON): same shape as `ai-brainstorm` — use `verdict` for the
judge's findings, carry `session_id` into the next round, log `duration_seconds`,
`cost_usd` (claude) / `tokens` (codex). Always inspect `git_guard.mutated_tree`.
If `ok` is false, read `error`, `attempts`, and the `.raw/round-N-judge.attemptK.*.log`
files to diagnose.

Note: the shared runner only schema-validates the `ai-brainstorm` ledgers, not
the findings ledger — so you parse the judge's findings block yourself. If the
judge emits a malformed or missing ledger, re-prompt it (its resumed session) to
re-emit just the fenced JSON block in the required shape before you proceed.

## Findings ledger schema

The judge emits exactly one fenced JSON block per round:

```json
{
  "findings": [
    {
      "id": "F1",
      "severity": "blocker|important|nit",
      "dimension": "correctness|edge-cases|security|conventions|simplicity|tests|architecture|performance|prod-readiness|docs",
      "file": "src/auth.ts",
      "line": "42 or 40-48",
      "claim": "What is wrong, specifically.",
      "evidence": "Why it is a problem — concrete, checkable.",
      "fix_suggestion": "What to do about it.",
      "pre_existing": false,
      "status": "open|resolved|rebutted|acknowledged"
    }
  ],
  "verdict": "CHANGES_REQUESTED|CLEAN"
}
```

You add, per finding, your response when you act on it:
`"response": {"action": "fixed|rebutted|deferred", "evidence": "...", "note": "..."}`.

`verdict: "CLEAN"` from the judge with no open blocker/important finding is the
stop signal — but verify the latest round actually engaged the change; a thin
rubber-stamp on round 1 is not a real review (run another judge round asking for
genuine scrutiny).

## Lite mode (quick pre-commit review)

Lite mode is the fast path: you are about to commit and want a different model to
review your change first, with the least possible ceremony and token spend. It
keeps the **core invariants** of the full review — the judge is a *different*,
*read-only* model that reads the *live* tree itself and keeps *one resumed
session* across rounds — but strips everything built for auditability.

**Lite does not find fewer problems than the full review.** It judges the same
dimensions and reports the same findings at the same severities — it highlights
everything the full flow would. What it trades away is *ceremony*, not detection:
no on-disk record, no JSON ledger, no PR/branch scope. Do not undersell it to the
user as a shallower check; it is the full review's eye with the full review's
paperwork removed.

**What it drops (vs. the full flow), and why it is cheaper:**

- **No `reviews/<slug>/` record.** No `review.md`, `state.json`, `scope.md`,
  `findings.json`, per-round logs, or `review-summary.md`. You track the few open
  findings in your own working context and summarize in chat. The *only* thing on
  disk is the mechanically-required prompt file + `.raw/` logs the runner always
  writes (gitignored runtime output).
- **No JSON findings ledger.** The judge returns a short prose list, not a
  schema-validated block — so there is no ledger to merge, no ledger-retry round,
  and far fewer output tokens. (Keep the lite prompt free of the headings/keys in
  "Findings ledger schema" so the shared runner's ledger validator stays off.)
- **Scope is always the uncommitted change** (`git diff HEAD` + untracked). No
  scope negotiation, no PR/branch mode — if the user wants a branch/PR review or a
  real audit, use the full flow instead.
- **Tight defaults:** one judge, stop threshold `blocker + important`, **`max_rounds = 2`**
  (often just one fix pass). It still reviews the **full dimension set** (the same
  ten as the full flow) — leading with correctness — so nothing the full review
  would catch slips through; it just reports them in the compact format below.

**Extra token savings to apply:**

- **Use a cheap/fast judge model.** Set `model` in the config to a small model:
  for a `claude` judge, `"model": "claude-haiku-4-5-20251001"`; for `codex`, pass
  a faster model via `model`. Default codex (`model: null`) is fine too — it
  reports no dollar cost, just tokens.
- **Skip the paid claude probe** in preflight: `run_round.py --check --no-probe-claude`
  (or skip preflight entirely if a judge round already ran this session).
- **Keep the prompt minimal** — the lite templates in `references/review-prompts.md`
  ("Judge lite — round 1" / "Judge lite — re-review") are deliberately short; do
  not pad them with the full dimension catalogue.
- **Loop only on `blocker`/`important`.** Nits are listed once and not chased.

**Lite flow:**

0. **Clean stale logs.** Before starting, wipe the throwaway log dir from any
   previous lite run — `rm -rf reviews/.lite` — so this run starts fresh and old
   prompts/output do not pile up. (It is gitignored runtime output; safe to
   delete.)
1. **Confirm in one line** what is under review (uncommitted changes) and the
   judge. Default judge `codex`; offer `claude` (haiku) if codex is unavailable.
   If `git diff HEAD` is empty *and* there are no untracked files, say so and stop.
2. **Read your own diff** (`git diff HEAD`, `git status`) — briefly; you still need
   enough understanding to fix or rebut.
3. **Judge round 1.** Build the prompt from the *Judge lite — round 1* template,
   write it to a `.raw/` prompt file, and run one agent via `run_round.py` with
   `raw_dir` = `reviews/.lite/.raw` (a single fixed throwaway dir — no per-review
   slug). `session_id: null`. Read back `verdict` and the returned `session_id`;
   check `git_guard.mutated_tree`.
4. **Apply fixes.** For each `blocker`/`important` finding: confirm at the cited
   `file:line`, then fix it minimally in the working tree, or rebut it with
   evidence. Note nits but do not chase them. No per-finding files — track them in
   chat.
5. **Round 2 (re-review), only if you fixed/rebutted anything.** Resume the judge's
   session with the *Judge lite — re-review* template (short). If it returns
   `CLEAN`, stop. If `blocker`/`important` remain and `max_rounds` is reached, stop
   and report what is still open — let the user decide whether to commit anyway.
6. **Report in chat** (no deliverable file): one or two lines — outcome
   (clean / clean-with-nits / open items left), what the judge caught and what you
   changed, and any nits worth a follow-up. Then the user commits.
7. **Clean up the logs.** Once the review finishes successfully (judge returned
   `CLEAN`, or you have reported the remaining open items), remove the throwaway
   log dir — `rm -rf reviews/.lite` — so nothing is left behind before the commit.

The config and `run_round.py` call are identical to the full flow (one judge
agent, resume by `session_id`), just with the lite prompt, the shared
`reviews/.lite/.raw` dir, and `max_rounds = 2`.

## Notes and edge cases

- **No changes to review.** If the scope's diff is empty (`git diff HEAD` + untracked
  for uncommitted; `git diff <base>...HEAD` for a branch), there is nothing to
  review — say so and stop. For a branch, an empty diff usually means a wrong base.
- **Judge CLI unavailable.** If `codex` is missing/unauthenticated, offer a fresh
  `claude` judge instead (same family, weaker check) and note the tradeoff.
- **The judge mutates the tree.** It must not. If `git_guard.mutated_tree` is true,
  stop and report — the read-only guarantee was violated.
- **The judge rubber-stamps.** A round-1 "looks fine, CLEAN" with no findings on a
  non-trivial change is suspect — run one more judge round demanding real,
  evidence-cited scrutiny across the dimensions before accepting it.
- **You start caving.** Watch yourself: do not "fix" a finding you believe is
  wrong just to end the loop. Rebut on evidence; convergence does not require
  agreement, it requires the *judge* to stop re-raising the point.
- **Resuming an interrupted review.** `state.json` holds the round, the judge's
  session id, scope, and threshold; `findings.json` holds the open findings — pick
  up where it stopped.
- **Cost.** Each judge round is real CLI usage; mention it if the user is
  cost-sensitive, and offer to set the judge to a cheaper/faster model.
- **Reviewing vs committing.** This skill reviews a *dirty* working tree on
  purpose — that is the whole point, unlike `ai-brainstorm` which wants a clean
  tree. Do not commit on the user's behalf unless asked.
