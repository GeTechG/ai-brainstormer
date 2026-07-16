# Dual diff-only mode (clean-context review for critical slices)

Read this when the change under review is a **critical slice** — schemas and
migrations, public API contracts, wire/serialization formats, patches to
fork/vendored code, security-sensitive paths — or when the user asks for **two
independent reviewers** or a **diff-only / clean-context** review. The judge
prompt for this mode is the *Judge diff-only* template in `review-prompts.md`.

**Why this mode exists.** Reviewers who receive *only the diff* in a *clean
context* — no author context, no rationalizations — have caught real
use-after-free and logic bugs that compiled and looked plausible. The standard
judge reviews the live repo in one resumed session; that is fine for lite and
ordinary diffs, but the resumed session gradually absorbs the respondent's
framing and rebuttals — exactly the channel a plausible-looking bug rides in on.
On a critical slice that channel is removed entirely, and the review is doubled:
**two independent reviewers, and divergence between their verdicts is itself a
signal.**

This mode keeps the full flow's ceremony (a `reviews/<slug>/` record, the JSON
findings ledger, the same scope shapes) but changes two things fundamentally:

1. **The reviewers receive only the diff — nothing else, ever.** Each round you
   freeze the scope's diff (`scope.diff_cmd`) and paste it verbatim into the
   prompt. No scope narrative, no change description, no author reasoning, no
   rebuttals, no prior-round findings. The reviewer may still *investigate* the
   read-only tree to verify what the diff touches (callers, definitions,
   lifetimes), but everything it *receives* is the diff. This is the one mode
   where you DO paste the diff — the frozen artifact is the review subject.
2. **Two independent reviewers per round, never resumed.** Both get the
   byte-identical prompt (only the finding-id prefix differs), run in parallel
   as two agents in one `run_round.py` config, and are never shown each other's
   output. Every round launches **fresh sessions** (`session_id: null`, always) —
   resuming would carry your framing into round 2, defeating the mode.

Everything else is unchanged from the full flow: reviewers are read-only,
findings are evidence-gated by `file:line`, you (respondent) are the only one
who writes, and `git_guard.mutated_tree` is inspected every invocation.

## Reviewer pair

Prefer two **different models** — default `codex` + `claude` (two families, two
blind spots). If only one CLI is available, run two fresh sessions of it and
tell the user the diversity is weaker. Findings ids are prefixed per reviewer so
they never collide:

| name         | id prefix | cli (default) |
|--------------|-----------|---------------|
| `reviewer-A` | `A-`      | `codex`       |
| `reviewer-B` | `B-`      | `claude`      |

## state.json for dual-diff

The single `judge` becomes a `reviewers` array. There is **no `session_id`** to
carry — sessions are single-use by design; the ids the runner returns land only
in the `.raw/` logs.

```json
{
  "slug": "schema-v2-contract",
  "scope_summary": "one-line summary of the critical slice under review",
  "scope": {"mode": "dual-diff", "base": null, "branch": null, "paths": [],
            "diff_cmd": "git diff HEAD"},
  "status": "round-1",
  "round": 1,
  "max_rounds": 4,
  "stop_threshold": "important",
  "dimensions": ["correctness","edge-cases","security","conventions","simplicity",
                 "tests","architecture","performance","prod-readiness","docs"],
  "reviewers": [
    {"name": "reviewer-A", "id_prefix": "A-", "cli": "codex", "model": null, "effort": null},
    {"name": "reviewer-B", "id_prefix": "B-", "cli": "claude", "model": null, "effort": null}
  ]
}
```

The scope shapes are the same as the full flow (uncommitted / branch / paths /
commit) — only the *delivery* changes: the diff is frozen and pasted, not re-run
by the judge.

## Reading the two ledgers — agreement and divergence

After each round, merge both ledgers into `findings.json` and compare:

- **Consensus findings** (both reviewers flag the same `file:line` problem,
  independently) — highest confidence; fix these first. Record the pairing in
  the merged ledger (`"consensus": ["A-2", "B-1"]`-style note in `response.note`
  or a shared comment).
- **Single-reviewer findings** — normal findings; still evidence-gated, still
  investigated and fixed or rebutted on their merits. One reviewer missing a
  bug the other caught is expected — that asymmetry is why there are two.
- **Verdict divergence** (one `CLEAN`, one `CHANGES_REQUESTED`, or the two read
  the *same lines* in contradictory ways) — **do not silently tie-break.**
  Investigate the disputed findings, and report the divergence to the user as a
  first-class signal: on a critical slice, if a clean-context reader cannot
  establish from the diff that the change is safe, that is itself actionable —
  clarify the code, add the missing test or comment, or shrink the diff — even
  when you believe the code is correct.

## Rebuttals without a resumed session

You never send rebuttals to these reviewers — a rebuttal is author
rationalization, the exact input this mode excludes. The semantics change
accordingly:

- A finding you **fix** closes when the next round's fresh pair does not raise
  it on the updated diff.
- A finding you **rebut** is recorded in `findings.json`
  (`response.action: "rebutted"`, with evidence) and closes only if the next
  fresh pair does **not** independently re-raise it. If a fresh, clean reviewer
  re-discovers the same problem after your rebuttal, the rebuttal is overruled —
  independent rediscovery from a cold context outweighs your reasoning.
  Surface it to the user rather than looping.

## Dual-diff flow

1. **Setup.** Confirm the scope shape and that this is a critical slice worth
   the doubled cost. Pick the pair (default `codex` + `claude`); preflight
   (`run_round.py --check`). Create `reviews/<slug>/` with the `reviewers`
   `state.json` above, `scope.md`, empty `findings.json`, seed `review.md`.
2. **Investigate your own change first** — same as Phase 1 of the full flow.
3. **Freeze the diff.** Run `scope.diff_cmd` and save the output verbatim to
   `rounds/round-N.diff`. Both prompts embed this exact text. If the diff is too
   large for a prompt, split it by file groups and run one pair per chunk (note
   the chunking in `review.md`); or shrink the scope.
4. **Reviewer round.** Build both prompts from the *Judge diff-only* template —
   byte-identical except `{ID_PREFIX}` — write them to
   `.raw/round-N-reviewer-A.prompt.md` / `-B.prompt.md`, and run **one config
   with both agents**, `session_id: null` for each, every round. Persist each
   verdict to `rounds/round-N.reviewer-A.judge.md` / `-B.judge.md`; merge both
   ledgers into `findings.json`; check `git_guard.mutated_tree`.
5. **Compare.** Mark consensus findings, note divergence (see above). If the
   verdicts diverge, tell the user now — do not wait for finalize.
6. **Respondent round.** Fix or rebut per the full flow's Phase 3, with the
   rebuttal semantics above. Log to `rounds/round-N.respondent.md`.
7. **Next round.** Regenerate the diff (your fixes are in it now) and go back to
   step 3 with a **new fresh pair**. Convergence: **both** reviewers return
   `CLEAN` (no open blocker/important from either) **in the same round**, or
   `max_rounds` is hit — then stop and document what stands, including any
   unresolved divergence.
8. **Finalize.** Same `review-summary.md` deliverable as the full flow, plus a
   short **"Agreement"** section: what both caught, what only one caught, and
   any verdict divergence with what it signaled.

## Cost

Two reviewers × rounds, and **no resume discount** — every round is a cold
session that re-reads from scratch. Roughly 2× a full review per round, more if
the diff is chunked. Quote this up front; the standard single-judge flow remains
the right default for non-critical changes.
