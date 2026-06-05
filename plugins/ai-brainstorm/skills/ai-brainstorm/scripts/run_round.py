#!/usr/bin/env python3
"""
run_round.py - run one round of an AI brainstorm.

Invokes each participating CLI agent (claude, codex, ...) in PARALLEL, in
read-only mode, capturing each agent's verdict text and its CLI session id.
This is the mechanical core of the ai-brainstorm skill: the orchestrator
(Claude running the skill) decides *what* prompt each agent gets and *whether*
to run another round; this script just runs the calls reliably.

Why a script and not raw Bash from the orchestrator:
  - Parallel subprocess management with timeouts is fiddly and error-prone.
  - The two CLIs have different flags, output formats, and failure modes.
    In particular `codex exec` can exit 0 even when it failed, so success
    must be judged by "did we actually get an answer", not the exit code.
  - Centralising that here means the orchestrator never has to remember CLI
    flags - it just writes a config and reads back structured JSON.

USAGE
  python3 run_round.py --config <round-config.json>   # run a round
  python3 run_round.py --check                        # preflight CLIs + auth
  python3 run_round.py --check --no-probe-claude      # skip paid claude probe

ROUND CONFIG JSON
{
  "project_dir": "/abs/path/to/project",   # agents run with this as cwd / -C
  "raw_dir":     "/abs/path/.../<slug>/.raw",  # debug logs go here
  "timeout_seconds": 1800,                 # per-agent wall-clock cap
  "round": 1,
  "agents": [
    {"name": "claude", "cli": "claude", "model": null,
     "session_id": null, "prompt_file": "/abs/prompt-claude.md"},
    {"name": "codex",  "cli": "codex",  "model": null,
     "session_id": null, "prompt_file": "/abs/prompt-codex.md"}
  ]
}
  - session_id null/absent  -> fresh session (round 1)
  - session_id set          -> resume that session (round 2+)
  - model null/absent       -> the CLI's default model

RESULT JSON (printed to stdout)
{
  "ok": true,
  "round": 1,
  "git_guard": {"available": true, "mutated_tree": false, ...},
  "results": [
    {"name": "claude", "cli": "claude", "ok": true,
     "session_id": "<feed this into next round's config>",
     "verdict": "<full text of the agent's answer>",
     "prompt_chars": 12000,
     "prompt_hash": "sha256:...",
     "exit_code": 0, "duration_seconds": 123.4, "timed_out": false,
     "cost_usd": 0.42,
     "tokens": {"input": 12, "output": 800, "cache_read": 40000,
                "cache_creation": 0, "total": 40812},
     "error": null}

`cost_usd` is the dollar cost when the CLI reports one (claude), else null
(codex reports none). `tokens` is a normalized usage summary for both CLIs, so
cost can be logged symmetrically even when `cost_usd` is null. Either may be
null if the CLI did not report usage.
  ]
}

This script writes ONLY into raw_dir (raw stdout/stderr for debugging). It
never touches the curated brainstorms/ files - that is the orchestrator's job.
Standard library only; no dependencies.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor


# --------------------------------------------------------------------------
# subprocess helper
# --------------------------------------------------------------------------

def _run(cmd, cwd, stdin_text, timeout):
    """Run a command, feed stdin_text, return (code, stdout, stderr, secs, timed_out).

    Uses Popen so that on timeout we can kill the process and still recover
    whatever partial output it produced - a long investigation that overran
    may still have written a usable verdict.
    """
    start = time.time()
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(input=stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except Exception:
            stdout, stderr = "", ""
    return proc.returncode, stdout or "", stderr or "", time.time() - start, timed_out


def _iter_json_lines(text):
    """Yield every parseable JSON object found line-by-line in text."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                yield json.loads(line)
            except Exception:
                continue


def _last_json_object(text):
    """Return the last parseable top-level JSON object in text, or None.

    `claude -p --output-format json` prints a single compact JSON object, but
    scanning from the end is robust to any stray warning lines printed first.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    found = None
    for obj in _iter_json_lines(text):
        found = obj
    return found


def _fenced_json_objects(text):
    """Yield parseable JSON objects from fenced ```json blocks."""
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text,
                             re.DOTALL | re.IGNORECASE):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except Exception:
            continue


# Composite ledger used by the symmetric_deliberation mode. Unlike the
# adversarial-review ledgers (one top-level array), this is three arrays in one
# fenced JSON block; each maps to its required item keys.
_DELIBERATION_SCHEMAS = {
    "options": ("id", "summary", "proposed_by"),
    "claims": ("id", "claim", "supports", "decision_critical", "evidence",
               "challenged_by", "status", "resolution_evidence"),
    "positions": ("agent", "current_option", "changed_from", "change_evidence",
                  "suspect_flip"),
}


def _expected_ledger_kind(prompt_text):
    # Symmetric-deliberation mode emits one composite ledger (options/claims/
    # positions). Detect it first — it is a distinct heading from the
    # adversarial-review objection/response ledgers.
    if (prompt_text.rfind("## Deliberation ledger") >= 0
            or '"claims": [' in prompt_text):
        return "deliberation"
    response_pos = prompt_text.rfind("## Objection ledger response")
    objection_pos = prompt_text.rfind("## Objection ledger")
    if response_pos >= 0 or objection_pos >= 0:
        if response_pos >= objection_pos:
            return "responses"
        return "objections"
    response_pos = prompt_text.rfind('"responses": [')
    objection_pos = prompt_text.rfind('"objections": [')
    if response_pos >= 0 or objection_pos >= 0:
        if response_pos >= objection_pos:
            return "responses"
        return "objections"
    if '"responses": [' in prompt_text:
        return "responses"
    if '"objections": [' in prompt_text:
        return "objections"
    return None


def _validate_deliberation_block(verdict):
    """Validate the composite symmetric-deliberation ledger.

    Unlike the objection/response ledgers (one top-level array), this ledger
    carries three arrays — options, claims, positions — in one fenced JSON
    block. All three must be present and every item must carry its required
    keys, so the orchestrator's machine convergence check (every
    decision_critical claim resolved, no suspect_flip) has the fields it needs.
    """
    for obj in _fenced_json_objects(verdict):
        if not isinstance(obj, dict):
            continue
        if not all(key in obj for key in _DELIBERATION_SCHEMAS):
            continue
        for key, required in _DELIBERATION_SCHEMAS.items():
            value = obj.get(key)
            if not isinstance(value, list):
                return "`%s` is not an array" % key
            for idx, item in enumerate(value):
                if not isinstance(item, dict):
                    return "%s[%d] is not an object" % (key, idx)
                missing = [k for k in required if k not in item]
                if missing:
                    return "%s[%d] missing %s" % (key, idx, ", ".join(missing))
        return None
    return ("missing fenced JSON block with top-level `options`, `claims`, and "
            "`positions` arrays")


def _validate_ledger_block(verdict, expected):
    """Return None when the expected fenced JSON ledger block is valid."""
    if not expected:
        return None
    if expected == "deliberation":
        return _validate_deliberation_block(verdict)
    required = ("id", "claim", "required_evidence", "severity", "status")
    if expected == "responses":
        required = ("id", "response", "evidence", "answer_change")

    for obj in _fenced_json_objects(verdict):
        value = obj.get(expected) if isinstance(obj, dict) else None
        if not isinstance(value, list):
            continue
        for idx, item in enumerate(value):
            if not isinstance(item, dict):
                return "%s[%d] is not an object" % (expected, idx)
            missing = [key for key in required if key not in item]
            if missing:
                return "%s[%d] missing %s" % (
                    expected, idx, ", ".join(missing))
        return None
    return "missing fenced JSON block with top-level `%s` array" % expected


def _ledger_retry_prompt(previous_verdict, validation_error, expected):
    if expected == "deliberation":
        schema = """```json
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
```"""
    elif expected == "responses":
        schema = """```json
{
  "responses": [
    {
      "id": "J1-O1",
      "response": "conceded|rebutted",
      "evidence": "Concrete file/line/command/section evidence.",
      "answer_change": "What changed, or why no change is needed."
    }
  ]
}
```"""
    else:
        schema = """```json
{
  "objections": [
    {
      "id": "J1-O1",
      "claim": "Specific lead claim or omission being challenged.",
      "required_evidence": "What would close this objection.",
      "severity": "high|medium|low",
      "status": "open|closed",
      "closed_by": null,
      "closure_evidence": null
    }
  ]
}
```"""
    return """READ-ONLY: do not modify, create, or delete files. Do not read `brainstorms/`. Stay inside the project.

Your previous answer could not be used by the orchestrator because its machine-readable objection ledger was invalid.

Validation error: %s

Return a corrected answer now. Keep the substantive content, but include exactly one fenced JSON block matching this schema:

%s

Previous answer:

--- BEGIN PREVIOUS ANSWER ---
%s
--- END PREVIOUS ANSWER ---
""" % (validation_error, schema, previous_verdict)


# --------------------------------------------------------------------------
# claude
# --------------------------------------------------------------------------

def _extract_text_from_content(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _parse_claude_stream(stdout):
    """Best-effort parser for `claude --output-format stream-json`.

    Claude Code stream events have changed over time, so this accepts both the
    documented result object and common assistant/content/delta shapes. The
    important reliability property is that timeout runs can still return the
    session id and any assistant text printed before the process was killed.
    """
    session_id = None
    usage = None
    cost_usd = None
    result_obj = None
    text_parts = []
    assistant_text = ""

    for ev in _iter_json_lines(stdout):
        if ev.get("session_id"):
            session_id = ev["session_id"]
        if isinstance(ev.get("usage"), dict):
            usage = ev.get("usage")
        if isinstance(ev.get("total_cost_usd"), (int, float)):
            cost_usd = ev.get("total_cost_usd")

        typ = ev.get("type")
        if typ == "result" or ev.get("subtype") in ("success", "error"):
            result_obj = ev
            continue

        if isinstance(ev.get("result"), str):
            text_parts.append(ev["result"])
        if isinstance(ev.get("delta"), str):
            text_parts.append(ev["delta"])
        if isinstance(ev.get("text"), str):
            text_parts.append(ev["text"])

        msg = ev.get("message")
        if isinstance(msg, dict):
            if isinstance(msg.get("usage"), dict):
                usage = msg.get("usage")
            text = _extract_text_from_content(msg.get("content"))
            if text:
                assistant_text = text
        text = _extract_text_from_content(ev.get("content"))
        if text:
            assistant_text = text

    if result_obj:
        if result_obj.get("session_id"):
            session_id = result_obj["session_id"]
        if isinstance(result_obj.get("usage"), dict):
            usage = result_obj.get("usage")
        if isinstance(result_obj.get("total_cost_usd"), (int, float)):
            cost_usd = result_obj.get("total_cost_usd")

    verdict = ""
    if result_obj and isinstance(result_obj.get("result"), str):
        verdict = result_obj.get("result", "").strip()
    if not verdict:
        verdict = (assistant_text or "".join(text_parts)).strip()
    return result_obj, verdict, session_id, usage, cost_usd


def run_claude(agent, project_dir, prompt_text, timeout):
    """Run the Claude Code CLI headless, with file-editing tools disabled.

    The Claude CLI exposes no OS-level read-only sandbox flag, so the agent
    runs in bypassPermissions mode (so a headless run never hangs on a
    permission prompt) with the Write/Edit/NotebookEdit tools denied - it can
    investigate the project freely but cannot modify files via its editing
    tools (`Bash` remains for read-only use; this is not an OS sandbox like
    codex's).

    Plan mode is deliberately NOT used: in headless mode it diverts the agent's
    answer into a separate plan file and returns only a short pointer, which
    breaks verdict capture. `stream-json` is used instead of final-only JSON so
    a timeout can still recover the session id and partial assistant text.
    """
    cmd = [
        "claude", "-p", "--output-format", "stream-json",
        # Newer claude CLIs reject `-p --output-format stream-json` without
        # `--verbose`; it streams the same JSONL events the parser already reads.
        "--verbose",
        "--include-partial-messages",
        "--permission-mode", "bypassPermissions",
        "--disallowedTools", "Write,Edit,MultiEdit,NotebookEdit",
    ]
    if agent.get("session_id"):
        cmd += ["--resume", agent["session_id"]]
    if agent.get("model"):
        cmd += ["--model", agent["model"]]

    code, out, err, secs, timed_out = _run(cmd, project_dir, prompt_text, timeout)

    obj, verdict, session_id, usage, cost_usd = _parse_claude_stream(out)
    if obj is None and not verdict:
        tail = (err or out)[-600:].strip()
        return _result(agent, code, secs, timed_out, out, err, ok=False,
                       verdict="", session_id=agent.get("session_id"),
                       cost_usd=None,
                       error="could not parse claude stream-json output. tail: " + tail)

    is_error = bool(obj and obj.get("is_error"))
    if obj and obj.get("subtype") not in (None, "success"):
        is_error = True
    ok = (not is_error) and bool(verdict) and not timed_out
    error = None
    if timed_out and verdict:
        error = "timed out after %ds (partial answer recovered)" % timeout
    elif timed_out:
        error = "timed out after %ds" % timeout
    elif is_error:
        error = "claude reported error (subtype=%s)" % (obj or {}).get("subtype")
    elif not verdict:
        error = "claude returned an empty result"
    res = _result(agent, code, secs, timed_out, out, err, ok=ok,
                  verdict=verdict,
                  session_id=session_id or agent.get("session_id"),
                  cost_usd=cost_usd,
                  tokens=_token_summary(usage), error=error)
    res["usage"] = usage
    return res


# --------------------------------------------------------------------------
# codex
# --------------------------------------------------------------------------

def run_codex(agent, project_dir, prompt_text, timeout, last_msg_file):
    """Run the Codex CLI headless, in read-only sandbox.

    `--sandbox read-only` is an OS-level sandbox: the agent physically cannot
    write files. `-o` mirrors the final answer to a file. The session id is the
    `thread_id` from the first `thread.started` JSONL event - feed it back to
    `codex exec resume` for later rounds.

    Note: `codex exec` can exit 0 even on failure, so success is judged by
    whether an actual answer came back, not by the exit code.
    """
    common = [
        "--json", "--skip-git-repo-check",
        "-c", "sandbox_mode=read-only",
        "-c", "approval_policy=never",
        "-o", last_msg_file,
    ]
    if agent.get("session_id"):
        # resume keeps the original session's working directory; no -C here.
        cmd = ["codex", "exec", "resume", agent["session_id"], "-"] + common
    else:
        cmd = ["codex", "exec"] + common + ["-C", project_dir]
    if agent.get("model"):
        cmd += ["-m", agent["model"]]

    # clear any stale -o file from a previous attempt
    try:
        os.remove(last_msg_file)
    except OSError:
        pass

    code, out, err, secs, timed_out = _run(cmd, project_dir, prompt_text, timeout)

    session_id = agent.get("session_id")
    usage = None
    last_agent_msg = ""
    for ev in _iter_json_lines(out):
        if ev.get("thread_id"):
            session_id = ev["thread_id"]
        elif ev.get("session_id"):
            session_id = ev["session_id"]
        if ev.get("type") == "item.completed":
            item = ev.get("item", {})
            if item.get("type") == "agent_message" and item.get("text"):
                last_agent_msg = item["text"]
        if ev.get("type") == "turn.completed":
            usage = ev.get("usage")

    verdict = ""
    try:
        with open(last_msg_file, "r", encoding="utf-8") as fh:
            verdict = fh.read().strip()
    except Exception:
        pass
    if not verdict:
        verdict = last_agent_msg.strip()

    ok = bool(verdict) and not timed_out
    error = None
    if timed_out and not verdict:
        error = "timed out after %ds (no answer recovered)" % timeout
    elif timed_out:
        error = "timed out after %ds (partial answer recovered)" % timeout
    elif not verdict:
        tail = (err or out)[-600:].strip()
        error = "codex produced no agent message. tail: " + tail
    # codex reports no dollar cost, so surface its tokens in the symmetric
    # `tokens` field; keep the raw usage object too for full fidelity.
    res = _result(agent, code, secs, timed_out, out, err, ok=ok,
                  verdict=verdict, session_id=session_id, cost_usd=None,
                  tokens=_token_summary(usage), error=error)
    res["usage"] = usage
    return res


# --------------------------------------------------------------------------
# shared
# --------------------------------------------------------------------------

def _token_summary(usage):
    """Normalize a CLI usage object to {input, output, cache_*, total} or None.

    claude and codex report token usage under different key names; collapsing
    both to one small schema lets the orchestrator log usage symmetrically -
    codex returns no dollar cost, so its tokens are the only comparable signal.
    """
    if not isinstance(usage, dict):
        return None

    def _g(*keys):
        for k in keys:
            v = usage.get(k)
            if isinstance(v, (int, float)):
                return int(v)
        return 0

    inp = _g("input_tokens", "input")
    out = _g("output_tokens", "output")
    cache_read = _g("cache_read_input_tokens", "cached_input_tokens")
    cache_create = _g("cache_creation_input_tokens")
    total = inp + out + cache_read + cache_create
    if total == 0:
        return None
    return {"input": inp, "output": out, "cache_read": cache_read,
            "cache_creation": cache_create, "total": total}


def _result(agent, code, secs, timed_out, stdout, stderr, *, ok, verdict,
            session_id, cost_usd, error, tokens=None):
    return {
        "name": agent["name"],
        "cli": agent["cli"],
        "ok": ok,
        "session_id": session_id,
        "verdict": verdict,
        "prompt_chars": None,
        "prompt_hash": None,
        "exit_code": code,
        "duration_seconds": round(secs, 1),
        "timed_out": timed_out,
        "cost_usd": cost_usd,
        "tokens": tokens,
        "error": error,
        "_stdout": stdout,
        "_stderr": stderr,
    }


def _is_retryable(res):
    """Decide whether a failed agent run deserves one automatic retry.

    Transient failures (network drop, "socket connection closed", rate limit,
    5xx, an unparseable JSON blob from a half-sent response) are worth one
    retry. Timeouts are NOT - the agent already spent its full wall-clock
    budget, and a second full run would likely overrun again. Auth failures are
    NOT - they will fail identically until the user logs in, so retrying just
    burns time and money.
    """
    if res["ok"] or res["timed_out"]:
        return False
    err = (res.get("error") or "").lower()
    if not err:
        return False
    auth_markers = ("auth", "login", "logged in", "unauthor", "401", "403",
                    "credential", "api key", "api-key", "forbidden",
                    "permission denied")
    if any(m in err for m in auth_markers):
        return False
    return True


def run_agent(agent, cfg):
    project_dir = cfg["project_dir"]
    raw_dir = cfg["raw_dir"]
    timeout = int(cfg.get("timeout_seconds", 1800))
    rnd = cfg.get("round", 0)

    try:
        with open(agent["prompt_file"], "r", encoding="utf-8") as fh:
            prompt_text = fh.read()
    except Exception as exc:
        return _result(agent, -1, 0.0, False, "", "", ok=False, verdict="",
                       session_id=agent.get("session_id"), cost_usd=None,
                       error="could not read prompt_file: %s" % exc)

    cli = agent["cli"]
    sys.stderr.write("  [%s] starting (%s)...\n" % (agent["name"], cli))
    sys.stderr.flush()

    if cli not in ("claude", "codex"):
        return _result(agent, -1, 0.0, False, "", "", ok=False, verdict="",
                       session_id=agent.get("session_id"), cost_usd=None,
                       error="unknown cli: %s (expected claude or codex)" % cli)

    def _stamp_prompt_telemetry(res, active_prompt):
        res["prompt_chars"] = len(active_prompt)
        res["prompt_hash"] = "sha256:" + hashlib.sha256(
            active_prompt.encode("utf-8")).hexdigest()
        return res

    def _invoke(prompt_override=None, agent_override=None):
        active_prompt = prompt_text if prompt_override is None else prompt_override
        active_agent = agent if agent_override is None else agent_override
        if cli == "claude":
            return _stamp_prompt_telemetry(
                run_claude(active_agent, project_dir, active_prompt, timeout),
                active_prompt)
        last_msg = os.path.join(raw_dir, "round-%s-%s.codex-last.txt"
                                % (rnd, agent["name"]))
        return _stamp_prompt_telemetry(
            run_codex(active_agent, project_dir, active_prompt, timeout, last_msg),
            active_prompt)

    attempts = []

    def _record_attempt(res):
        attempts.append({
            "ok": res.get("ok"),
            "timed_out": res.get("timed_out"),
            "exit_code": res.get("exit_code"),
            "duration_seconds": res.get("duration_seconds"),
            "error": res.get("error"),
            "_stdout": res.get("_stdout", ""),
            "_stderr": res.get("_stderr", ""),
        })

    # One automatic retry for transient (non-timeout, non-auth) failures - a
    # dropped socket or rate-limit should not cost a whole manual rerun.
    res = _invoke()
    _record_attempt(res)
    if _is_retryable(res):
        sys.stderr.write("  [%s] transient failure (%s) - retrying once...\n"
                         % (agent["name"], res["error"]))
        sys.stderr.flush()
        res = _invoke()
        _record_attempt(res)

    expected_ledger = _expected_ledger_kind(prompt_text)
    validation_error = None
    if res.get("ok") and expected_ledger:
        validation_error = _validate_ledger_block(res.get("verdict") or "",
                                                  expected_ledger)
    if validation_error and not res.get("timed_out"):
        sys.stderr.write("  [%s] invalid ledger (%s) - retrying with schema...\n"
                         % (agent["name"], validation_error))
        sys.stderr.flush()
        retry_agent = dict(agent)
        retry_agent["session_id"] = res.get("session_id") or agent.get("session_id")
        retry_prompt = _ledger_retry_prompt(res.get("verdict") or "",
                                            validation_error, expected_ledger)
        res = _invoke(prompt_override=retry_prompt, agent_override=retry_agent)
        res["ledger_retry"] = True
        res["ledger_validation_error"] = _validate_ledger_block(
            res.get("verdict") or "", expected_ledger)
        if res["ledger_validation_error"]:
            res["ok"] = False
            res["error"] = "invalid ledger after retry: " + res["ledger_validation_error"]
        _record_attempt(res)
    elif validation_error:
        res["ledger_validation_error"] = validation_error
        res["ok"] = False
        res["error"] = "invalid ledger: " + validation_error

    # persist raw output for debugging, then drop it from the returned JSON
    for idx, attempt in enumerate(attempts, start=1):
        attempt["log_files"] = {}

    res.pop("_stdout", "")
    res.pop("_stderr", "")

    for attempt_no, attempt in enumerate(attempts, start=1):
        out_data = attempt.pop("_stdout", "")
        err_data = attempt.pop("_stderr", "")
        for suffix, data in (("stdout", out_data), ("stderr", err_data)):
            try:
                attempt_path = os.path.join(raw_dir, "round-%s-%s.attempt%s.%s.log"
                                            % (rnd, agent["name"], attempt_no, suffix))
                with open(attempt_path, "w", encoding="utf-8") as fh:
                    fh.write(data)
                attempts[attempt_no - 1]["log_files"][suffix] = attempt_path
                legacy_path = os.path.join(raw_dir, "round-%s-%s.%s.log"
                                           % (rnd, agent["name"], suffix))
                with open(legacy_path, "w", encoding="utf-8") as fh:
                    fh.write(data)
            except Exception:
                pass
    res["attempts"] = attempts

    status = "ok" if res["ok"] else ("FAILED: " + str(res["error"]))
    sys.stderr.write("  [%s] done in %ss - %s\n"
                     % (agent["name"], res["duration_seconds"], status))
    sys.stderr.flush()
    return res


# --------------------------------------------------------------------------
# preflight check
# --------------------------------------------------------------------------

def do_check(probe_claude=True):
    report = {"ok": True, "clis": {}}
    for cli in ("claude", "codex"):
        path = shutil.which(cli)
        info = {"installed": bool(path), "path": path, "version": None}
        if path:
            try:
                ver = subprocess.run([cli, "--version"], capture_output=True,
                                     text=True, timeout=20)
                info["version"] = (ver.stdout or ver.stderr).strip().splitlines()[0]
            except Exception as exc:
                info["version"] = "could not read version: %s" % exc
        else:
            report["ok"] = False
        report["clis"][cli] = info

    # codex exposes an explicit auth check; claude has none headless-friendly,
    # so its auth is verified implicitly by the first real round.
    if report["clis"]["codex"]["installed"]:
        try:
            st = subprocess.run(["codex", "login", "status"],
                                capture_output=True, text=True, timeout=20)
            text = (st.stdout + st.stderr).strip()
            lines = text.splitlines()
            logged_in = [line for line in lines if "Logged in" in line]
            report["clis"]["codex"]["auth"] = (
                logged_in[-1] if logged_in else (lines[-1] if lines else "unknown"))
            if not logged_in:
                report["ok"] = False
        except Exception as exc:
            report["clis"]["codex"]["auth"] = "could not check: %s" % exc

    # claude has no headless auth-status command, so auth/connectivity requires
    # a tiny paid round-trip unless the caller explicitly opts out.
    if probe_claude and report["clis"]["claude"]["installed"]:
        try:
            pr = subprocess.run(
                ["claude", "-p", "--output-format", "json",
                 "--permission-mode", "bypassPermissions"],
                input="reply OK", capture_output=True, text=True, timeout=60)
            obj = _last_json_object(pr.stdout or "")
            if obj and obj.get("subtype") == "success" and not obj.get("is_error"):
                report["clis"]["claude"]["probe"] = "ok"
            else:
                tail = (pr.stderr or pr.stdout or "")[-300:].strip()
                report["clis"]["claude"]["probe"] = (
                    "FAILED: " + (tail or "no success response"))
                report["ok"] = False
        except Exception as exc:
            report["clis"]["claude"]["probe"] = "could not probe: %s" % exc
            report["ok"] = False

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


# --------------------------------------------------------------------------
# git guard
# --------------------------------------------------------------------------

def _git_root(project_dir):
    try:
        res = subprocess.run(["git", "-C", project_dir, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def _status_paths(project_dir, raw_dir):
    root = _git_root(project_dir)
    if not root:
        return None, None
    try:
        rel_raw = os.path.relpath(os.path.abspath(raw_dir), root)
    except Exception:
        rel_raw = None
    try:
        res = subprocess.run(["git", "-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
                             capture_output=True, text=True, timeout=30)
    except Exception:
        return root, None
    if res.returncode != 0:
        return root, None

    entries = []
    for line in res.stdout.splitlines():
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if rel_raw and (path == rel_raw or path.startswith(rel_raw.rstrip("/") + "/")):
            continue
        entries.append(line)
    return root, sorted(entries)


def git_guard_before(cfg):
    project_dir = cfg["project_dir"]
    raw_dir = cfg["raw_dir"]
    root, entries = _status_paths(project_dir, raw_dir)
    if root is None:
        return {
            "available": False,
            "mutated_tree": None,
            "warning": "mutation detection unavailable: project_dir is not inside a git worktree",
        }
    if entries is None:
        return {
            "available": False,
            "mutated_tree": None,
            "git_root": root,
            "warning": "mutation detection unavailable: could not read git status",
        }
    return {"available": True, "git_root": root, "before": entries}


def git_guard_after(cfg, before):
    if not before.get("available"):
        return before
    root, after = _status_paths(cfg["project_dir"], cfg["raw_dir"])
    if after is None:
        return {
            "available": False,
            "mutated_tree": None,
            "git_root": before.get("git_root") or root,
            "warning": "mutation detection unavailable: could not read git status after round",
        }
    before_entries = before.get("before") or []
    added = [x for x in after if x not in before_entries]
    removed = [x for x in before_entries if x not in after]
    return {
        "available": True,
        "git_root": before.get("git_root") or root,
        "mutated_tree": bool(added or removed),
        "before_dirty": bool(before_entries),
        "added_or_changed": added,
        "removed_or_reverted": removed,
        "note": "Uses git status; gitignored files are not detected.",
    }


def validate_raw_dir(project_dir, raw_dir):
    """Return an error string if raw_dir is not an allowed script-write path."""
    project_abs = os.path.abspath(project_dir)
    raw_abs = os.path.abspath(raw_dir)
    try:
        common = os.path.commonpath([project_abs, raw_abs])
    except ValueError:
        return "raw_dir must be inside project_dir"
    if common != project_abs:
        return "raw_dir must be inside project_dir"
    return None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Run one round of an AI brainstorm.")
    ap.add_argument("--config", help="path to round config JSON")
    ap.add_argument("--check", action="store_true",
                    help="verify the CLIs are installed and authenticated")
    ap.add_argument("--probe-claude", action="store_true",
                    help="with --check, run a tiny (paid) claude round-trip "
                         "to verify its auth/connectivity (default)")
    ap.add_argument("--no-probe-claude", action="store_true",
                    help="with --check, skip the tiny paid claude auth probe")
    args = ap.parse_args()

    if args.check:
        return do_check(probe_claude=(not args.no_probe_claude))

    if not args.config:
        ap.error("either --config or --check is required")

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    raw_dir_error = validate_raw_dir(cfg["project_dir"], cfg["raw_dir"])
    if raw_dir_error:
        print(json.dumps({"ok": False, "error": raw_dir_error}, ensure_ascii=False))
        return 1

    os.makedirs(cfg["raw_dir"], exist_ok=True)
    agents = cfg["agents"]
    if not agents:
        print(json.dumps({"ok": False, "error": "no agents in config"}))
        return 1

    sys.stderr.write("Running round %s with %d agent(s) in parallel...\n"
                     % (cfg.get("round", "?"), len(agents)))
    sys.stderr.flush()

    guard_before = git_guard_before(cfg)

    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        results = list(pool.map(lambda a: run_agent(a, cfg), agents))

    git_guard = git_guard_after(cfg, guard_before)

    out = {
        "ok": all(r["ok"] for r in results),
        "round": cfg.get("round"),
        "git_guard": git_guard,
        "results": results,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
