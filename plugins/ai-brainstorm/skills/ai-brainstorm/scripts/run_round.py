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
  python3 run_round.py --check                        # preflight CLIs (free)
  python3 run_round.py --check --probe-claude         # + tiny paid claude probe

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
  "results": [
    {"name": "claude", "cli": "claude", "ok": true,
     "session_id": "<feed this into next round's config>",
     "verdict": "<full text of the agent's answer>",
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
import json
import os
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


# --------------------------------------------------------------------------
# claude
# --------------------------------------------------------------------------

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
    breaks verdict capture. `--output-format json` hands back the full answer
    plus the session id and cost.
    """
    cmd = [
        "claude", "-p", "--output-format", "json",
        "--permission-mode", "bypassPermissions",
        "--disallowedTools", "Write,Edit,MultiEdit,NotebookEdit",
    ]
    if agent.get("session_id"):
        cmd += ["--resume", agent["session_id"]]
    if agent.get("model"):
        cmd += ["--model", agent["model"]]

    code, out, err, secs, timed_out = _run(cmd, project_dir, prompt_text, timeout)

    obj = _last_json_object(out)
    if obj is None:
        tail = (err or out)[-600:].strip()
        return _result(agent, code, secs, timed_out, out, err, ok=False,
                       verdict="", session_id=agent.get("session_id"),
                       cost_usd=None,
                       error="could not parse claude JSON output. tail: " + tail)

    is_error = bool(obj.get("is_error")) or obj.get("subtype") != "success"
    verdict = (obj.get("result") or "").strip()
    ok = (not is_error) and bool(verdict) and not timed_out
    error = None
    if timed_out:
        error = "timed out after %ds" % timeout
    elif is_error:
        error = "claude reported error (subtype=%s)" % obj.get("subtype")
    elif not verdict:
        error = "claude returned an empty result"
    return _result(agent, code, secs, timed_out, out, err, ok=ok,
                   verdict=verdict, session_id=obj.get("session_id"),
                   cost_usd=obj.get("total_cost_usd"),
                   tokens=_token_summary(obj.get("usage")), error=error)


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

    def _invoke():
        if cli == "claude":
            return run_claude(agent, project_dir, prompt_text, timeout)
        last_msg = os.path.join(raw_dir, "round-%s-%s.codex-last.txt"
                                % (rnd, agent["name"]))
        return run_codex(agent, project_dir, prompt_text, timeout, last_msg)

    # One automatic retry for transient (non-timeout, non-auth) failures - a
    # dropped socket or rate-limit should not cost a whole manual rerun.
    res = _invoke()
    if _is_retryable(res):
        sys.stderr.write("  [%s] transient failure (%s) - retrying once...\n"
                         % (agent["name"], res["error"]))
        sys.stderr.flush()
        res = _invoke()

    # persist raw output for debugging, then drop it from the returned JSON
    stdout = res.pop("_stdout", "")
    stderr = res.pop("_stderr", "")
    for suffix, data in (("stdout", stdout), ("stderr", stderr)):
        try:
            path = os.path.join(raw_dir, "round-%s-%s.%s.log"
                                % (rnd, agent["name"], suffix))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(data)
        except Exception:
            pass

    status = "ok" if res["ok"] else ("FAILED: " + str(res["error"]))
    sys.stderr.write("  [%s] done in %ss - %s\n"
                     % (agent["name"], res["duration_seconds"], status))
    sys.stderr.flush()
    return res


# --------------------------------------------------------------------------
# preflight check
# --------------------------------------------------------------------------

def do_check(probe_claude=False):
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
            line = (st.stdout or st.stderr).strip().splitlines()
            report["clis"]["codex"]["auth"] = line[0] if line else "unknown"
            if "Logged in" not in report["clis"]["codex"]["auth"]:
                report["ok"] = False
        except Exception as exc:
            report["clis"]["codex"]["auth"] = "could not check: %s" % exc

    # claude has no headless auth-status command, so its auth is normally
    # verified implicitly by the first real round (keeping --check free).
    # --probe-claude opts into an explicit, tiny, *paid* round-trip that
    # surfaces auth/connectivity problems now instead of mid-brainstorm.
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
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Run one round of an AI brainstorm.")
    ap.add_argument("--config", help="path to round config JSON")
    ap.add_argument("--check", action="store_true",
                    help="verify the CLIs are installed and authenticated")
    ap.add_argument("--probe-claude", action="store_true",
                    help="with --check, also run a tiny (paid) claude round-trip "
                         "to verify its auth/connectivity now; off by default")
    args = ap.parse_args()

    if args.check:
        return do_check(probe_claude=args.probe_claude)

    if not args.config:
        ap.error("either --config or --check is required")

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    os.makedirs(cfg["raw_dir"], exist_ok=True)
    agents = cfg["agents"]
    if not agents:
        print(json.dumps({"ok": False, "error": "no agents in config"}))
        return 1

    sys.stderr.write("Running round %s with %d agent(s) in parallel...\n"
                     % (cfg.get("round", "?"), len(agents)))
    sys.stderr.flush()

    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        results = list(pool.map(lambda a: run_agent(a, cfg), agents))

    out = {
        "ok": all(r["ok"] for r in results),
        "round": cfg.get("round"),
        "results": results,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
