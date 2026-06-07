# Prompt templates for brainstorm agents

The orchestrator fills these in, writes each to a prompt file, and passes the
file to `run_round.py`. Each agent runs **headless and non-interactive** — it
cannot ask a question mid-run, so the templates route questions through a
dedicated section instead.

Write every prompt in **English**. All agent-to-agent communication — both the
prompts you write and the responses the agents produce — is in English, no matter
what language the user speaks. The agents' verdicts, critiques, ledgers, and
`## QUESTIONS FOR USER` therefore come back in English too. Only your *direct*
interaction with the user follows the user's language: when you relay an agent's
questions to the user, ask in the user's language; when you write the
user-facing deliverable, write it in the user's language. You translate at that
boundary. Placeholders look like `{LIKE_THIS}`.

The brainstorm has two **modes** (see `SKILL.md`):

- **`adversarial_review`** (default) — two orchestration roles: one **lead** (its
  answer becomes the answer under review) and one or more **judges**
  (adversarially review it). Templates: *Round 1*, *Judge turn*, *Lead turn*.
- **`symmetric_deliberation`** (opt-in, for open "where to take the project"
  questions) — every agent is an equal **participant**; positions collide and the
  conclusion is derived from the clash, never averaged toward agreement.
  Templates: *Round 1* (shared), *Symmetric deliberation turn*, *Symmetric final
  stance*.

In both modes, roles take effect only from round 2 — round 1 is one identical
independent study for everyone, and agents are not told any role.

---

## Shared rules block

Prepend this to every prompt, every round. It is what keeps agents independent
and the project safe.

```
You are an AI agent in a structured brainstorm run by an orchestrator. Ground
rules — they matter:

- You are READ-ONLY. Investigate the project freely (read, search, run
  read-only commands) but do not modify, create, or delete any file. Your
  thinking is your output; the orchestrator records it for you.
- Do NOT read anything under the `brainstorms/` directory. It holds other
  agents' notes and the orchestrator's records. Reading it would bias you and
  defeat the point of independent analysis.
- Keep your investigation inside the project directory. Do not go reading
  unrelated parts of the filesystem (for example `~/.claude/`) — the brainstorm
  is about the project, not the tooling that runs it.
- You run non-interactively — you cannot ask a question and wait. If you need a
  decision or fact only the user has, put it under a `## QUESTIONS FOR USER`
  heading at the end. The orchestrator will get answers and pass them back.
- Be rigorous and concrete. Cite specific files, lines, commands, and evidence.
  Vague claims are worthless here; checkable ones move the brainstorm forward.
- Use the project's available skills, tools and MCP servers as needed.
- Write your entire response in English. This is an inter-agent exchange
  conducted in English; the orchestrator translates for the user where needed.
```

### Compact resumed-round rules block

Use this shorter block from round 2 onward unless you need to re-emphasize a
rule after a failure.

```
READ-ONLY: do not modify, create, or delete files. Do not read `brainstorms/`.
Stay inside the project. Ask only under `## QUESTIONS FOR USER`. Be concrete:
cite files, lines, commands, and evidence. Respond in English.
```

---

## Round 1 — independent study

Every agent gets the **same** prompt — there is no per-role version. Round 1's
value is a clean, unbiased, independent view; roles begin at round 2.

### Body

```
{SHARED_RULES_BLOCK}

# This round's goal

Produce the most accurate, best-evidenced independent view you can. Do not
optimize for any later role or for defending your answer — just get the analysis
right. Other agents are studying the same topic independently; the orchestrator
decides afterward how the answers are used.

# Brainstorm topic

{TOPIC}

# Project

The project to investigate is at: {PROJECT_DIR}

# Your task for this round

Investigate the project as deeply as the topic needs, then deliver your own
independent answer. Do not hedge — take a clear position and defend it.

Structure your answer like this:

## Position {#pos}
Your recommendation in 2-4 sentences. What should be done?

## Reasoning {#reasoning}
The key arguments, each backed by concrete evidence from the project
(file paths, code, measurements, command output).

## Risks and tradeoffs {#risks}
What could go wrong with your recommendation; what you are trading away.

## Alternatives considered and rejected {#alternatives}
Other options and the specific reason each loses.

## Confidence {#confidence}
High / medium / low, and what would change your mind.

## QUESTIONS FOR USER
Only if something genuinely blocks a good answer. Omit the heading entirely
if you have none.
```

---

## Judge turn — critique the lead's answer (rounds 2, 4, …)

Sent to each judge on its **resumed** session, so it still remembers its own
round-1 study. Each judge works alone — it never sees other judges.

```
{ROUND_RULES_BLOCK}

# Brainstorm topic

{TOPIC_REMINDER}

# This is judge round {ROUND}

Here is the lead analyst's current answer. Review it critically.

--- BEGIN LEAD ANALYST'S ANSWER ---
{LEAD_ANSWER}
--- END LEAD ANALYST'S ANSWER ---

# Current objection ledger

The orchestrator maintains this machine-readable ledger across rounds. Reuse
existing ids when an objection is the same issue; create new ids only for new
substantive objections.

```json
{OBJECTIONS_JSON}
```

{USER_ANSWERS_SECTION}

# Your task for this round

Your job is to make the final answer correct and complete. That has two halves,
and a useful judge does both: **attack what is weak**, and **propose what you
would do instead**. Compare the lead's answer against your own analysis.

- Name concrete errors, unsupported claims, missed risks, and weak reasoning.
- Where the lead must dig deeper, say specifically what it should investigate.
- **Put your own solution on the table.** You studied this problem
  independently in round 1 — do not hide that view. Lay out the approach you
  would take, including where it agrees with the lead and where it diverges, so
  the lead sees a real alternative and not only a list of complaints. A judge
  that only attacks gives the lead one side of the problem; your aim is the best
  answer, which means contributing your own.
- Be objective. Do not manufacture disagreement to look rigorous, and do not
  wave through something doubtful. If a point is a genuine judgment call, or
  needs a fact only the user has, put it under `## QUESTIONS FOR USER`.
- Acknowledge what the lead got right — a judge that only attacks is as useless
  as one that only nods. Your aim is the best answer, not a body count.
- Before you drop an objection, **re-derive it against your own round-1
  analysis**, not against the lead's rhetoric. Concede only when the lead's
  *evidence* refutes you — confident phrasing, repetition, or appeals to move on
  are not evidence. An objection abandoned without new evidence is capitulation,
  not agreement, and it ships a worse answer to the user.

You may investigate the project further to ground an objection or your proposal.

Structure your answer like this:

## What the lead got right {#got-right}
Briefly — the parts that hold up.

## Your proposed solution {#proposal}
Your own answer to the topic, grounded in your round-1 study and any further
investigation — not a critique of the lead, but what *you* would do. State your
position, the key reasoning with concrete evidence (files, lines, commands), and
where it agrees with or diverges from the lead. Keep it self-contained: the lead
will read this as a real alternative to weigh, not as a rehash of your objections.

## Objections {#objections-summary}
One concise line per substantive point. The JSON ledger below is the source of
truth, so do not duplicate long prose here.

## Objection ledger {#ledger}
Include one fenced JSON block:

```json
{
  "objections": [
    {
      "id": "J1-O1",
      "claim": "The specific lead claim or omission being challenged.",
      "required_evidence": "What would close this objection.",
      "severity": "high|medium|low",
      "status": "open|closed",
      "closed_by": null,
      "closure_evidence": null
    }
  ]
}
```

For a closed objection, `closed_by` must name the lead round/section and
`closure_evidence` must cite the new evidence that resolved it. Do not close an
objection merely because the lead sounds confident or wants to move on.

## What the lead should investigate further {#investigate}
Specific, actionable investigation requests.

## QUESTIONS FOR USER
Only if needed; omit the heading otherwise.

## JUDGE STATUS
Exactly one of:
  OBJECTIONS REMAIN — followed by a one-line summary of what is still wrong.
  NO FURTHER OBJECTIONS — followed by one line on why the answer now holds.
```

**Section-id delta input for `{LEAD_ANSWER}` (rounds ≥ 4).**
On the lead's *first* appearance to a judge (round 2) always paste the full
answer above. From round 4 on, the judge already saw the previous lead answer in
its resumed session, so you may replace `{LEAD_ANSWER}` with the lead's
`## LEAD STATUS` line **verbatim** plus only the section-id blocks the lead
marked changed since the version you last showed *this* judge, **verbatim**,
under this marker:

```
--- BEGIN LEAD ANSWER DELTA (base: round N-2; unchanged sections omitted, they are
    already in your session history) ---
```

This is still verbatim — it drops duplicated unchanged text, not fidelity.
Always send the full `STATUS` line, always keep the reconstructed complete
answer in `sessions/<lead>/round-N.md`, and fall back to full paste on doubt.

---

## Lead turn — respond to the judges (rounds 3, 5, …)

Sent to the lead on its **resumed** session. Paste every judge's latest
critique, labelled by judge.

```
{ROUND_RULES_BLOCK}

# Brainstorm topic

{TOPIC_REMINDER}

# This is lead round {ROUND}

The judge(s) reviewed your answer. Here are all of their critiques.

--- BEGIN JUDGE CRITIQUES ---
{JUDGE_CRITIQUES}
--- END JUDGE CRITIQUES ---

# Current objection ledger

Respond by id to every open objection in this ledger.

```json
{OBJECTIONS_JSON}
```

{USER_ANSWERS_SECTION}

# Your task for this round

Address every objection. Where a judge asked you to investigate something, do
that investigation before you answer.

- Where a judge is right: concede it explicitly, fix your answer, and say what
  changed. Changing your mind on evidence is strength.
- Where a judge is wrong: rebut it with concrete evidence. Do NOT concede just
  to end the argument — an unearned concession ships a worse answer to the user.
- **Each judge also proposed its own solution (`## Your proposed solution`).**
  Treat it as a serious alternative, not as instructions. Weigh it on evidence:
  adopt the parts that genuinely improve your answer (and credit them in
  `## Alternatives` or the relevant section), and reject the parts that do not,
  saying why. Do NOT wholesale-copy a judge's proposal — your answer must stay
  your own reasoned position, now informed by theirs.
- Where a point cannot be settled objectively: say so, and put any user-facing
  question under `## QUESTIONS FOR USER`.

Structure your answer like this:

## Responses to objections {#responses-summary}
One concise line per id. The JSON response below is the source of truth, so do
not duplicate long prose here.

## Objection ledger response {#ledger-response}
Include a fenced JSON block with exactly this shape:

```json
{
  "responses": [
    {
      "id": "J1-O1",
      "response": "conceded|rebutted",
      "evidence": "Concrete file/line/command/section evidence, or a reference to New investigation done this round.",
      "answer_change": "What changed in the revised answer, or why no change is needed."
    }
  ]
}
```

Every open id must appear exactly once. A concession or rebuttal without
evidence is not valid.

## New investigation done this round {#investigation}
What you checked in the project because the judges asked, and what you found.

## Revised answer sections
Use stable section ids. In round 3, emit every section below in full. From round
5 onward, emit only sections whose content changed, plus `## LEAD STATUS` in
full. The orchestrator reconstructs the full answer from these section-id
blocks.

### Position {#pos}
Current recommendation in 2-4 sentences.

### Reasoning {#reasoning}
Current key arguments backed by evidence.

### Risks and tradeoffs {#risks}
Current risks and tradeoffs.

### Alternatives considered and rejected {#alternatives}
Current rejected alternatives and why they lose.

### Confidence {#confidence}
Current confidence and what would change your mind.

## QUESTIONS FOR USER
Only if needed; omit the heading otherwise.

## LEAD STATUS
Exactly one of:
  REVISED — followed by a one-line summary of what changed.
  NOTHING TO CHANGE — followed by one line on why the answer stands as-is.
```

**Section-id delta input for `{JUDGE_CRITIQUES}` (rounds ≥ 5).**
On a judge's *first* critique to the lead (round 3) always paste that judge's
full critique. From round 5 on, you may replace a judge's entry with its
`## JUDGE STATUS` line **verbatim** plus only the section-id blocks that are new
or changed since the critique you last showed the lead, **verbatim**, under:

```
--- BEGIN <JUDGE> CRITIQUE DELTA (base: round N-2; unchanged sections omitted,
    already in your session history) ---
```

Same rules: verbatim-diff, never paraphrase; always send the full STATUS line;
keep each full critique in `sessions/<judge>/round-N.md`; fall back to full paste
on any doubt.

---

## Symmetric deliberation turn — collide positions (mode `symmetric_deliberation`, rounds 2, 3, …)

Sent to **every** participant on its resumed session, each round. There is no
lead and no judge: each agent argues its own position, attacks the strongest
*opposing* position on evidence, and may move only when evidence forces it. The
orchestrator injects the other participants' material (agents still never read
`brainstorms/`).

The stop criterion is **decoupled from agreement** — the deliberation ends when
every decision-critical claim is resolved with evidence, not when everyone nods.
A compromise-in-the-middle reached only to finish is forbidden.

```
{ROUND_RULES_BLOCK}

# Brainstorm topic

{TOPIC_REMINDER}

# This is symmetric deliberation round {ROUND}

This is a deliberation among equals — there is no lead and no judge. Your goal is
the most defensible answer to the topic, derived from the collision of opposing
views, NOT a compromise that averages them. Do not soften your position to reach
agreement; agreement is not the goal and is not required to finish.

Here are the other participants' current positions, pasted by the orchestrator.

--- BEGIN OTHER PARTICIPANTS' POSITIONS ---
{OTHER_POSITIONS}
--- END OTHER PARTICIPANTS' POSITIONS ---

# Current deliberation ledger

The orchestrator maintains this machine-readable ledger across rounds. Reuse
existing ids; create new ids only for genuinely new options or claims.

```json
{DELIBERATION_JSON}
```

{USER_ANSWERS_SECTION}

# Your task for this round

- **State your current position** as one of the `options` (or propose a new
  option with an id). Take a clear stance; do not hedge.
- **Articulate the strongest opposing view** — the best version of the position
  you most disagree with, stated fairly (steelman, not strawman). Then attack it
  on evidence.
- **Attack claims, not agents.** Challenge specific claims by id; supply the
  evidence that would resolve them. Never argue from another agent's tone,
  confidence, or wish to move on.
- **Mark `decision_critical` claims** — the ones that, if resolved, actually
  decide between options. These are what convergence is measured on.
- **Do NOT propose a compromise-middle option without evidence.** A new
  synthesis option is allowed ONLY if it cites concrete `accepted` claims from
  **both** sides; a synthesis with no cross-side claim ids is unearned and will
  be rejected by the orchestrator (`unearned_synthesis`).
- **Move only on evidence.** You may change your `current_option`, but every
  change must carry `change_evidence` (the specific new evidence or resolved
  claim that moved you). A flip with no evidence is capitulation, not agreement,
  and will be flagged `suspect_flip`.
- **Resolving a claim you challenged** requires you to explicitly drop the
  challenge with `resolution_evidence`. An unaddressed challenge keeps the claim
  `unresolved`; it does not silently become `accepted`.

You may investigate the project further to ground a claim or your position.

Structure your answer like this:

## Your position {#position}
Which option you back right now, in 2-4 sentences, and the decisive reason.

## Strongest opposing view {#opposing}
The best case for the position you most disagree with, stated fairly — then where
and why the evidence breaks it.

## Claims and challenges {#claims-summary}
One concise line per substantive claim or challenge you are adding or resolving
this round. The JSON ledger below is the source of truth; do not duplicate long
prose here.

## Deliberation ledger {#ledger}
Include exactly one fenced JSON block with all three arrays:

```json
{
  "options": [
    {"id": "OPT-A", "summary": "One concrete direction the project could take.", "proposed_by": "claude"}
  ],
  "claims": [
    {
      "id": "C1",
      "claim": "A decision-relevant assertion.",
      "supports": "OPT-A",
      "decision_critical": true,
      "evidence": "Concrete file/line/command/measurement evidence.",
      "challenged_by": [],
      "status": "open|accepted|rejected|unresolved",
      "resolution_evidence": null
    }
  ],
  "positions": [
    {
      "agent": "claude",
      "current_option": "OPT-A",
      "changed_from": null,
      "change_evidence": null,
      "suspect_flip": false
    }
  ]
}
```

Rules for the ledger:
- `challenged_by` lists the agents currently challenging a claim. A challenged
  claim becomes `accepted` only when **every** challenger drops its challenge
  with `resolution_evidence`; otherwise it stays `unresolved`.
- `status: "accepted"` or `"rejected"` for a `decision_critical` claim REQUIRES a
  non-empty `resolution_evidence`. `open` means still contested; `unresolved`
  means challenged and not yet settled.
- A `position` whose `current_option` differs from `changed_from` MUST give
  `change_evidence`, else set `suspect_flip: true` yourself.

## QUESTIONS FOR USER
Only if needed; omit the heading otherwise.

## DELIBERATION STATUS
Exactly one of:
  OPEN CLAIMS REMAIN — followed by a one-line summary of which decision-critical
  claims are still open or unresolved.
  ALL DECISION-CRITICAL CLAIMS RESOLVED — followed by one line naming your
  recommended option; note this is NOT a claim of consensus, only that the
  evidence is in.
```

**Section-id delta input for `{OTHER_POSITIONS}` (rounds ≥ 3).**
On a counterpart's *first* appearance (round 2) paste each other participant's
full position. From round 3 on, replace a participant's entry with its
`## DELIBERATION STATUS` line **verbatim** plus only the section-id blocks it
marked changed since the version you last showed *this* participant, **verbatim**,
under:

```
--- BEGIN <PARTICIPANT> POSITION DELTA (base: round N-1; unchanged sections
    omitted, already in your session history) ---
```

At N=2 each participant sees exactly one counterpart; from N≥3 the orchestrator
pastes each of the other N-1 participants under its own labelled block. Keep the
reconstructed full position in `sessions/<agent>/round-N.md`; fall back to full
paste on doubt; always send full content to a fresh auditor.

---

## Symmetric final stance — machine-readable closing position (mode `symmetric_deliberation`)

Sent to **every** participant once the deliberation ledger shows no `open` (and
no unexplained `suspect_flip`) on decision-critical claims, OR at the round cap.
Each participant commits a final, machine-readable stance. **Consensus is not
required** — a participant may end in dissent, and the orchestrator preserves
that in the final plan rather than erasing it.

```
{ROUND_RULES_BLOCK}

# Brainstorm topic

{TOPIC_REMINDER}

# Final stance

The deliberation has reached the point where the decision-critical claims are
resolved with evidence (or the round cap was hit). Commit your final position.

- Do NOT change your stance now to match anyone else. If you still disagree,
  state your dissent — it will be recorded faithfully, not averaged away.
- Your recommended option must be justified by the specific `accepted`/`rejected`
  claims that led you there, by id.
- If you back a synthesis option, it MUST cite `accepted` claims from more than
  one original side; a synthesis without cross-side claim ids is unearned.

# Current deliberation ledger

```json
{DELIBERATION_JSON}
```

Structure your answer like this:

## Final position {#final-position}
Your recommended option and the decisive reasoning in 2-4 sentences.

## FINAL STANCE
Include exactly one fenced JSON block:

```json
{
  "agent": "claude",
  "recommended_option": "OPT-A",
  "supporting_claims": ["C1", "C3"],
  "is_synthesis": false,
  "cross_side_claims": [],
  "dissents_from": [],
  "unresolved_at_close": []
}
```

- `supporting_claims` — the resolved claim ids that justify your recommendation.
- `is_synthesis` true requires `cross_side_claims` to list `accepted` claim ids
  from more than one original side (otherwise the stance is unearned).
- `dissents_from` — options/agents you still disagree with, if any.
- `unresolved_at_close` — claim ids you consider still unresolved (empty if none).
```

---

## `{USER_ANSWERS_SECTION}`

If the user answered questions since the last round, include:

```
# Answers from the user

The user answered questions raised earlier. Treat these as authoritative:

{QUESTIONS_AND_ANSWERS}
```

Otherwise leave `{USER_ANSWERS_SECTION}` empty.

The prompt is in English, so translate the user's questions and answers into
English in `{QUESTIONS_AND_ANSWERS}` before pasting them — keep the meaning exact.

---

## Tips for the orchestrator

- Keep the topic semantically identical. Round 1 uses full `{TOPIC}`; resumed
  rounds should use a compact `{TOPIC_REMINDER}` such as "Same topic as round 1;
  use your session history and the pasted counterpart material."
- Paste answers and critiques **verbatim**. "Verbatim" forbids *paraphrasing or
  softening* — it does **not** forbid a verbatim section-id delta. From later
  rounds paste only changed sections word-for-word when the receiving agent has
  already seen the full base. Always label which judge said what.
- The lead sees judges' **round-2+ critiques, including the `## Your proposed
  solution` each judge writes there** — but never their verbatim independent
  round-1 answers. The proposal is re-articulated fresh in the critique turn, so
  the lead gets the judge's constructive view without the round-1 file leaking.
  Judges see the lead's **answer**, never each other. Respect this — it keeps the
  review independent (the lead still must reason, not copy) and bounds tokens.
- If a judge's critique is a thin rubber-stamp ("looks fine"), that is not a
  real review — run the judge turn again and ask for genuine engagement.
- If the lead concedes a point with no evidence, that is capitulation, not
  agreement — in the next lead prompt, tell it to concede only what the
  evidence forces.
- Use `objections.json` as the source of truth for convergence. `## JUDGE
  STATUS` is a readable summary; every unresolved or closed issue must still be
  represented by id in the ledger block.
