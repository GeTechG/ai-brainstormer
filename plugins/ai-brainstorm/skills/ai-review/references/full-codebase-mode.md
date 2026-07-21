# Full-codebase mode (audit the whole project, not a diff)

Read this when the user wants the **entire existing codebase** reviewed, not a
change — "audit the whole project", "review all the code".
The judge prompts for this mode are the *Judge specialist* templates in
`review-prompts.md`.

This mode keeps the full flow's ceremony (a `reviews/<slug>/` record, a JSON
findings ledger, resumable rounds) but changes two things fundamentally:

1. **Scope is the whole tree, and nothing is "pre-existing".** There is no
   introduced-vs-pre-existing split — every real problem you can ground in
   `file:line` is in scope and blocks. The three diff-mode suppressions
   (review-only-introduced-lines; `pre_existing` does not block; no new nits on
   unchanged code) **do not apply here**, because by definition all code is
   "under review" and there is no "unchanged" baseline.
2. **The single judge becomes a fan-out of cross-model specialists.** One judge
   cannot hold a whole repo in context, and a generalist sweep over everything
   goes shallow. So you launch **several judge specialists in parallel**, each a
   separate cross-model session that hunts **one class of problem only** across
   the code; their findings merge into one ledger. This is the "split the search
   into parts" model.

Everything else is unchanged from the full flow: the judge is a different,
read-only model; it reads the live tree itself; each specialist keeps **one
resumed session** across rounds; convergence is "no open blocker/important in the
merged ledger"; and **you (respondent) are the only one who writes — you fix
sequentially**, one finding at a time, in the single working tree.

## Specialists (the search, split into parts)

Each specialist owns a narrow slice of the dimension catalogue and is told to
**ignore everything outside its slice** (another specialist owns it). Default
roster — **5 specialists** (adjust to the project: fewer for a small repo, more
or area-split for a large one):

| name          | id prefix | hunts only                                            |
|---------------|-----------|-------------------------------------------------------|
| `correctness` | `COR-`    | correctness/logic bugs + edge-cases & error handling  |
| `security`    | `SEC-`    | security: injection, secrets, authz, input validation |
| `design`      | `DES-`    | architecture + convention adherence + simplicity/reuse|
| `performance` | `PERF-`   | performance/efficiency — real problems only           |
| `tests-docs`  | `TST-`    | test coverage/quality + docs + production-readiness    |

Confirm the roster at setup (let the user trim, extend, or rename). Each
specialist is one agent in the `run_round.py` config, so one round = one config
with N agents run in parallel.

## Chunking by area (when the tree is too big)

If a specialist cannot cover the repo in one context, split it **by area**
(directory/module) too: `security__src-auth`, `security__src-api`, … — each its
own agent and session, scoped to one area. Decide granularity from repo size
(`git ls-files | wc -l`, source LOC). Keep the matrix sane:

- The runner launches **every agent in a config in parallel**. Do **not** put
  ~20 agents in one config — cap a single config at ~6 agents and run the rest as
  **additional sequential `run_round.py` invocations** (batches) within the same
  round. You fix only *after every batch of a round finishes*, so batching never
  races the git-guard.
- **Log what you did not cover.** If you cap areas or specialists, say so in
  `review.md` and the summary — silent truncation reads as "audited everything"
  when it wasn't.

## state.json for full-codebase

The single `judge` becomes a `specialists` array; each carries its own
`session_id`:

```json
{
  "slug": "audit-payments-service",
  "scope_summary": "full-codebase audit of the whole repository",
  "scope": {"mode": "full-codebase", "base": null, "branch": null, "paths": [],
            "list_cmd": "git ls-files"},
  "status": "round-1",
  "round": 1,
  "max_rounds": 4,
  "stop_threshold": "important",
  "dimensions": ["correctness","edge-cases","security","conventions","simplicity",
                 "tests","architecture","performance","prod-readiness","docs"],
  "specialists": [
    {"name": "correctness", "id_prefix": "COR-", "cli": "codex", "model": null,
     "effort": null, "session_id": null, "areas": []},
    {"name": "security", "id_prefix": "SEC-", "cli": "codex", "model": null,
     "effort": null, "session_id": null, "areas": []}
  ]
}
```

`areas: []` means the whole tree; otherwise it lists the directories that
specialist was scoped to. For an area-chunked cell, give each cell its own entry
with a unique `name` (e.g. `security__src-auth`) and the same `id_prefix`.

## Findings ledger across specialists

Each specialist emits its own findings ledger (same schema as the full flow, but
`pre_existing` is dropped — nothing is pre-existing here). **Prefix every id with
the specialist's `id_prefix`** (`SEC-1`, `COR-1`, `DES-2`, …) so ids never
collide, and merge all of them into one `findings.json`. Convergence is read from
the merged ledger: no `open` blocker/important from **any** specialist.

## Full-codebase flow

1. **Setup.** Settle the roster and (if needed) the area split; pick the judge
   from the other model family (`codex` when hosted by Claude Code, `claude`
   when hosted by Codex); preflight (`run_round.py --check`). Invent a
   `slug`, create `reviews/<slug>/`, write `scope.md` (whole-codebase scope), the
   `specialists` `state.json`, an empty `findings.json`, and seed `review.md`.
   **Warn on cost:** N specialists × rounds × areas CLI runs — tell the user the
   rough multiplier and let them cap N, areas, or `max_rounds`.
2. **Investigate the codebase yourself first** (`git ls-files`, read the main
   modules) — enough to fix and to rebut, same as Phase 1 of the full flow.
3. **Specialist round.** Build one prompt per specialist from the *Judge
   specialist — round 1 (full-codebase)* template (its dimension slice + its
   area), write each to `.raw/round-N-<name>.prompt.md`, and put a batch's
   specialists in one config (`session_id: null` in round 1; saved ids after).
   Run `run_round.py`; repeat for further batches if area-chunked. Map each
   result back by `name`: persist its verdict to `rounds/round-N.<name>.judge.md`,
   save its `session_id` into `state.json`, and merge its ledger into
   `findings.json`. Inspect `git_guard.mutated_tree` on **every** invocation.
4. **Respondent round (fix sequentially).** For every `open` blocker/important in
   the merged ledger: confirm it at the cited `file:line` — **a finding grounded
   there is treated as real and you fix it; that confirmation is the gate, there
   is no separate user-approval step.** Fix minimally in the project's style, one
   finding at a time in the single working tree. Rebut on evidence where a finding
   is wrong (do not cave); surface a genuine judgment call to the user. Record
   actions in `rounds/round-N.respondent.md` and `findings.json`.
5. **Re-sweep round.** Resume each specialist's session with the *Judge specialist
   — re-review (full-codebase re-sweep)* template: it re-checks its prior findings
   (resolved / still-open / rebutted) **and** raises any new real
   blocker/important it now sees in its slice. Unlike diff-mode re-review, this is
   a genuine full re-sweep — that is the whole point of full-codebase. Back to
   step 4 until convergence or `max_rounds`.
6. **Finalize.** Same `review-summary.md` deliverable as the full flow, plus one
   line naming which specialists ran, over which areas, and anything left
   uncovered.

## Cost

Full-codebase mode spends roughly N_specialists × N_areas × rounds CLI runs — far
more than a diff review. Quote the rough multiplier up front, start with the lean
default roster, and let the user cap specialists, areas, or `max_rounds` before
launching.
