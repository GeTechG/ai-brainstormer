# Prompt templates for the judge

The respondent (you, running the skill) fills these in, writes each to a prompt
file, and passes the file to `run_round.py`. The judge runs **headless and
non-interactive** — it cannot ask a question mid-run, so it routes anything it
needs through a dedicated section.

Write every prompt in **English**. All communication between you and the judge —
the prompts you write and the findings, ledgers, and `## QUESTIONS FOR USER` the
judge returns — is in English, no matter what language the user speaks. Only your
*direct* interaction with the user follows the user's language: relay the judge's
questions in the user's language and write the user-facing deliverable in the
user's language. You translate at that boundary. Placeholders look like
`{LIKE_THIS}`.

There are two judge prompts:
- **Judge round 1** — full review of the scope from a cold, clean session.
- **Judge re-review** (rounds ≥ 2) — short; sent to the *resumed* session after
  you have fixed/rebutted, so it remembers its own prior findings.

---

## Shared rules block

Prepend to every judge prompt.

```
You are a code-review JUDGE in a cross-model review. A different model wrote (or
is responsible for) the change; your job is to review it independently and well.
Ground rules — they matter:

- You are READ-ONLY. Investigate the project and the change freely (read, search,
  run read-only commands like `git diff`, `git status`, `git log`) but do not
  modify, create, or delete any file. Your findings are your output; the
  respondent records them.
- Review the LIVE working tree. Run `git diff HEAD` and `git status` yourself to
  see the current uncommitted change, including new untracked files. Do not trust
  a pasted snapshot — read the real code.
- Do NOT read anything under `reviews/` or `brainstorms/`. Those hold the
  orchestration records and would bias you. Stay inside the project directory.
- Be rigorous and concrete. EVERY finding must cite `file:line` and a checkable
  reason. A finding you cannot ground in specific code is not a finding — drop it.
- Do NOT inflate severity. Most issues are not blockers. Style preferences are
  nits and never block. Distinguish problems THIS change introduces from
  pre-existing issues you happen to notice (mark the latter `pre_existing: true`);
  pre-existing issues do not block.
- You run non-interactively. If you need a decision or fact only the user has, put
  it under `## QUESTIONS FOR USER`; the respondent will get an answer.
- Use the project's available skills, tools, and MCP servers as needed.
- Write your entire response in English. This is an inter-agent exchange
  conducted in English; the respondent translates for the user where needed.
```

### Compact resumed rules block (rounds ≥ 2)

```
READ-ONLY: do not modify, create, or delete files. Re-run `git diff HEAD` /
`git status` to see the CURRENT tree. Do not read `reviews/` or `brainstorms/`.
Cite file:line with checkable evidence. Do not inflate severity; no new nits on
unchanged code. Respond in English.
```

---

## Judge round 1 — full review

```
{SHARED_RULES_BLOCK}

# What to review

{SCOPE}

# Review dimensions

Review comprehensively, but ADAPT these to what this project actually is — do not
force an irrelevant dimension. Default your attention to correctness; do not bury
the review in style nits.

Core (always):
1. Correctness / logic — bugs, off-by-one, null/undefined, wrong conditionals,
   dead paths, "does it do what it claims".
2. Edge cases & error handling — unhandled exceptions, silent failures, swallowed
   errors; concurrency/races for concurrent code.
3. Security — injection, hardcoded secrets, unsafe deserialization/crypto, missing
   input validation, data/PII exposure.
4. Project-convention adherence — existing patterns, structure, naming, rules in
   CLAUDE.md / AGENTS.md.
5. Simplicity / reuse — duplication, over-engineering, reinventing existing utils.
6. Tests — new branches covered, tests assert real behavior, they pass.

Also in scope for this review:
7. Architecture / design — coupling, separation of concerns, integration.
8. Performance / efficiency — only when it is a REAL problem, not speculative.
9. Production readiness — migrations, backward compatibility, rollback safety.
10. Documentation / comments — completeness; comments left stale by the change.

# Severity

- blocker  — would break production or is a security hole.
- important — a real bug, missing case, or convention violation worth fixing.
- nit      — style/preference. Report at most ~5, then say "+N similar". Never blocks.

# Your task

Review the current uncommitted change against the dimensions above. Find the real
problems THIS change introduces. For each, give file:line and checkable evidence.
Acknowledge what is solid — a review that only attacks is as useless as one that
only nods, but do not manufacture issues to look thorough.

Structure your answer:

## Summary
2-4 sentences: overall health of the change and the headline issues.

## Findings
One concise line per finding (id, severity, file:line, the problem). The JSON
ledger below is the source of truth — do not duplicate long prose here.

## Findings ledger
Include exactly one fenced JSON block:

```json
{
  "findings": [
    {
      "id": "F1",
      "severity": "blocker|important|nit",
      "dimension": "correctness|edge-cases|security|conventions|simplicity|tests|architecture|performance|prod-readiness|docs",
      "file": "path/to/file",
      "line": "42 or 40-48",
      "claim": "What is wrong, specifically.",
      "evidence": "Why it is a problem — concrete and checkable.",
      "fix_suggestion": "What to do about it.",
      "pre_existing": false,
      "status": "open"
    }
  ],
  "verdict": "CHANGES_REQUESTED|CLEAN"
}
```

`verdict: "CLEAN"` only if you found no blocker or important finding. Otherwise
`CHANGES_REQUESTED`.

## QUESTIONS FOR USER
Only if a decision or fact only the user has blocks a finding. Omit otherwise.
```

---

## Judge re-review — rounds 2, 4, … (resumed session)

Sent to the judge's **resumed** session, so it still remembers every finding it
raised. Keep it short — do not re-explain the rules or re-list dimensions.

```
{COMPACT_RESUMED_RULES_BLOCK}

# Re-review

I have addressed your findings. Re-run the scope's diff ({DIFF_CMD}) and
`git status` to see the CURRENT change — my fixes are there as working-tree edits
or new commits — then update your ledger.

For each finding you raised before:
- If the new code resolves it → set `status: "resolved"` and name what fixed it in
  `evidence` (the concrete change you can see in the diff).
- If it still stands → keep it `open` and say what is still wrong.
- Where I pushed back, here is my reasoning — weigh it on evidence, not tone:

{RESPONDENT_REBUTTALS}

If my rebuttal holds up against the code, set that finding `status: "rebutted"`. If
it does not, keep it `open` and explain why the code still has the problem.

Raise a NEW finding only for a real problem you can ground in file:line — do not
add nits on code that did not change.

{USER_ANSWERS_SECTION}

Re-emit the full findings ledger (one fenced JSON block, same schema as before,
every finding with its current `status`), plus:

## DECISION
Exactly one of:
  CHANGES_REQUESTED — followed by one line naming the open blocker/important findings.
  CLEAN — followed by one line: no blocker or important finding remains.
```

---

## Judge lite — round 1 (quick pre-commit review)

For **lite mode** (see SKILL.md → "Lite mode"). Short, low-token, **no JSON
ledger**: the judge replies with a plain findings list, so there is nothing to
schema-validate and far fewer output tokens. Keep this prompt free of the words
`ledger`, `objections`, `responses`, `claims`, `"findings": [` etc. so the shared
runner's ledger validator stays off. Use a cheap/fast judge model.

```
You are a code-review JUDGE in a cross-model review, and you are READ-ONLY:
investigate freely (read, search, `git diff HEAD`, `git status`) but do NOT
modify, create, or delete any file. Do not read anything under `reviews/` or
`brainstorms/`.

This is a QUICK pre-commit pass. The change under review is the current
UNCOMMITTED state of this project — run `git diff HEAD` and `git status`
yourself (include new untracked files) and review only what this change
introduces. Note pre-existing issues at most in passing; they do not block.

Focus on REAL problems this change introduces, in this order of attention:
1. Correctness / logic bugs — wrong conditionals, off-by-one, null/undefined,
   dead paths, "does it do what it claims".
2. Edge cases & error handling — unhandled exceptions, silent/swallowed failures,
   obvious races in concurrent code.
3. Security — injection, hardcoded secrets, missing input validation, data/PII
   exposure.
Mention a convention or simplicity issue only if it is clearly worth fixing
before commit. Do not bury this in style nits.

Severity: `blocker` (breaks prod / security hole), `important` (a real bug or
missing case worth fixing), `nit` (style/preference — list at most ~3, never
blocks). Do NOT inflate severity. EVERY finding must cite `file:line` and a
concrete, checkable reason; if you cannot ground it, drop it.

Reply in English, in this exact shape, nothing fancier:

## Findings
One line each, ordered by severity:
`[F1] blocker — path/to/file:42 — what is wrong; suggested fix in a few words`
(write "none" if there are no blocker/important findings)

## VERDICT
Exactly one of:
  CLEAN — no blocker or important finding.
  CHANGES_REQUESTED — followed by the F-ids that are blocker/important.

## QUESTIONS
Only if a decision or fact only the user has blocks a finding; omit otherwise.
```

---

## Judge lite — re-review (resumed session)

Sent to the **resumed** lite session after you fixed/rebutted. Keep it tiny — it
still remembers its findings.

```
READ-ONLY: do not modify/create/delete files; do not read `reviews/` or
`brainstorms/`. Re-run `git diff HEAD` / `git status` to see the CURRENT tree.

I addressed your findings. For each one you raised: if the current code resolves
it, say "resolved" and name what fixed it; if it still stands, keep it and say
what is still wrong. Where I pushed back, weigh my reasoning on the evidence, not
the tone:

{RESPONDENT_REBUTTALS}

Raise a NEW finding only for a real blocker/important problem you can ground in
`file:line` — no new nits on unchanged code.

Reply in English, with the same compact shape:

## Findings
One line per still-open finding (id, severity, file:line, what remains). Write
"none" if nothing blocker/important remains.

## VERDICT
CLEAN (no blocker/important left) or CHANGES_REQUESTED (+ the open ids).
```

---

## `{SCOPE}` — how to describe what is under review

Default (uncommitted changes):

```
The change under review is the current UNCOMMITTED state of this project: the
output of `git status` and `git diff HEAD`, including any new untracked files.
Run those commands yourself to see it. Review only what this change introduces;
note pre-existing issues separately and do not block on them.
```

PR / branch (everything the branch introduces vs its base):

```
The change under review is this PR / branch: everything branch `{BRANCH}`
introduces relative to base `{BASE}`. Run `git diff {BASE}...{BRANCH}` (THREE
dots — the merge-base diff, so a base that moved ahead does not add noise) to see
it; `git log {BASE}..{BRANCH}` shows the commits. Review only what this branch
introduces. On re-review rounds, new fix commits will appear in this same diff.
```

User-specified paths:

```
The change under review is limited to these paths: {PATHS}. Run
`git diff HEAD -- {PATHS}` (and inspect new untracked files among them). Review
only changes within these paths.
```

User-specified single commit:

```
The change under review is commit {SHA}. Run `git show {SHA}` to see it. Review
only what this commit introduces.
```

---

## `{RESPONDENT_REBUTTALS}` and `{USER_ANSWERS_SECTION}`

`{RESPONDENT_REBUTTALS}` — for each finding you rebutted this round, one block:

```
- F3 (you flagged: <one-line>): <your evidence that it does not hold —
  file/line/command output>.
```

If you rebutted nothing this round, write "None this round — I fixed everything
you raised."

`{USER_ANSWERS_SECTION}` — if the user answered a question since the last round:

```
# Answers from the user

The user answered questions raised earlier. Treat these as authoritative:

{QUESTIONS_AND_ANSWERS}
```

Otherwise leave it empty. The prompt is in English, so translate the user's
questions and answers into English in `{QUESTIONS_AND_ANSWERS}` before pasting
them — keep the meaning exact.

---

## Tips for the respondent

- **Round 1 is full; re-reviews are short.** The resumed judge already holds the
  rules and its prior findings — re-pasting them wastes tokens and can confuse it.
- **Never paste the diff.** The judge reads the live repo itself; that is what
  keeps it reviewing the real, current code after each of your fixes. `{DIFF_CMD}`
  is `state.json`'s `scope.diff_cmd` (e.g. `git diff HEAD` or
  `git diff main...HEAD`) — the same command every round.
- **Parse the ledger, not the prose.** Convergence is "no open blocker/important
  finding", read from the JSON block. The `## DECISION` line is a human summary.
- **A thin rubber-stamp is not a review.** If round 1 comes back `CLEAN` with no
  findings on a non-trivial change, run another judge round demanding genuine,
  evidence-cited scrutiny.
- **Rebut, do not cave.** When you believe a finding is wrong, put your evidence
  in `{RESPONDENT_REBUTTALS}` rather than damaging the code. The judge must accept
  the rebuttal for the finding to close — that is the anti-capitulation control.
- **Fall back to a fuller prompt on doubt.** If the judge seems to have lost the
  rules or its prior findings, re-send the round-1 template's rules and dimensions.
```
