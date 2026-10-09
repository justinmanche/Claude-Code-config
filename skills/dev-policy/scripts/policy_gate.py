#!/usr/bin/env python3
"""Hard gates for the dev-policy skill: the moments code leaves the owner's hands.

The old design interrupted every reply (a Stop hook that blocked until the check
had passed on the current working state). That fought the normal case of an
orchestrating session whose background agents keep changing the shared checkout:
the state changed between runs and about ten status replies in a row were blocked.
This module gates the boundaries instead.

WHY THESE GATES AND NOT OTHERS (owner decision, 2026-10-07).
  - The check is enforced where code leaves the owner's hands: `git merge <branch>`
    into main, `git push` (also as a real git `pre-push` hook, so it holds for anyone
    who pushes) and `deploy-test.sh`. Each is denied unless `check.py` passed on the
    EXACT committed tree involved; the stamp is keyed by the git tree hash and is
    written only for a clean tree, so a pass can never be reused for different code.
  - A subagent that changed code is checked and blocked ONCE when it finishes, so it
    fixes failures before its report is delivered rather than leaving them for the
    session that merges it.
  - The one remaining Stop hook speaks only after a reply in which the main session
    itself edited code with no agents running. The owner chose no end-of-reply
    reminders, so it is never advice and is silent otherwise.
  - The bypass for a push is `--no-verify`, and every gate fails OPEN if the hook
    itself breaks: a broken gate must not lock the owner out of their own repository.

Modes (first argument; hook input JSON on stdin):
  pre-bash      PreToolUse on Bash. Denies `git merge <branch>` while on main, `git push`
                and `deploy-test.sh` unless check.py has PASSED on the exact committed
                tree involved (stamp keyed by the git tree hash), plus deploy
                preconditions (clean tree, no leftover agent worktrees) and the
                "a test suite was run" requirement.
  pre-handback  PreToolUse on SubagentHandback: same self-check as subagent-stop, for
                subagents that deliver their report through that tool (auto mode),
                where SubagentStop fires only after the report has been delivered.
  subagent-stop SubagentStop. When a subagent that changed code finishes, run the check
                and block ONCE with the failures so it fixes them before reporting.
  stop          Stop. One quiet end-of-reply hook: blocks only when the main session
                itself edited code since the last user message, no agents are running,
                and the check has not passed / tests were not run / hygiene has a
                must-fix item. Never a reminder, never advice; silent otherwise.
  pre-push      git `pre-push` hook (arguments: remote name, url; stdin: ref lines).
                Same push rule as the Bash gate, for anyone who pushes.

Output contracts (Claude Code hooks): allow = exit 0 with no stdout.
  PreToolUse   deny  -> {"hookSpecificOutput":{"hookEventName":"PreToolUse",
                         "permissionDecision":"deny","permissionDecisionReason":"..."}}
  Stop / SubagentStop block -> {"decision":"block","reason":"..."}
Always exit 0 from a Claude hook (exit 2 or a crash surfaces as a hook error). Any
unexpected exception fails OPEN (allow, silently; set DEV_POLICY_DEBUG=1 to see it).
pre-push is a git hook: exit 1 rejects the push.

Payload fields relied on (checked against https://code.claude.com/docs/en/hooks):
  all events    session_id, transcript_path, cwd, hook_event_name
  PreToolUse    tool_name, tool_input.command (Bash) / tool_input.message (SubagentHandback);
                agent_id + agent_type when fired inside a subagent
  Stop          stop_hook_active, last_assistant_message, background_tasks[] (type, status)
  SubagentStop  stop_hook_active, agent_id, agent_type, agent_transcript_path
Fields NOT relied on because the docs do not promise them: SubagentStop `cwd` being the
subagent's directory (the subagent's own sidecar file `agent-<id>.meta.json` next to its
transcript names its worktreePath; its transcript entries carry `cwd`; both are tried first).
"""
import hashlib
import json
import os
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devpolicy_common as dp  # noqa: E402

CHECK_SCRIPT = os.path.join(HERE, "check.py")
CHECK_CMD = "python3 ~/.claude/skills/dev-policy/scripts/check.py"
MAIN_BRANCHES = ("main", "master")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
AGENT_TASK_TYPES = ("subagent", "workflow", "teammate", "cloud session")
TERMINAL_STATUSES = ("completed", "failed", "killed", "cancelled", "canceled", "stopped", "done", "error")
DEFAULT_IMPL = r"(^|/)src/"
TEST_PATH_RE = re.compile(r"(\.test\.|\.spec\.|(^|/)__tests__/|(^|/)__integration__/|(^|/)e2e/|(^|/)tests?/)")
CHECK_TIMEOUT = 840


# ----------------------------------------------------------------------------------
# Shell command parsing. Enough of a shell grammar to find simple commands inside
# `a && b`, `a; b`, pipes, subshells, heredocs, `bash -c '...'`, and to follow `cd`.
# Anything it cannot understand yields no command (the gates then allow).
# ----------------------------------------------------------------------------------

class Cmd:
    __slots__ = ("words", "redirects", "cwd")

    def __init__(self, words, redirects, cwd):
        self.words = words
        self.redirects = redirects
        self.cwd = cwd


_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WRAPPERS = {"sudo", "command", "exec", "time", "nohup", "nice", "builtin", "then", "do", "else", "elif",
             "if", "while", "until", "!", "{", "}", "env"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}


def _match_close(s, i, open_ch, close_ch):
    """s[i] == open_ch; return the index just past the matching close, quote-aware. n on failure."""
    depth, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            i = j + 1
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _tokenize(s):
    toks = []  # ("w", text) | ("op", text) | ("r", operator, target)
    i, n = 0, len(s)
    cur, started = [], False
    pending = None  # redirect operator waiting for its target word
    heredocs = []  # (delimiter, strip_tabs) waiting for the body after the next newline

    def end_word():
        nonlocal cur, started, pending
        if not started:
            return
        w = "".join(cur)
        cur, started = [], False
        if pending is not None:
            op, pending = pending, None
            if op in ("<<", "<<-"):
                heredocs.append((w, op == "<<-"))
            toks.append(("r", op, w))
        else:
            toks.append(("w", w))

    while i < n:
        c = s[i]
        if c == "\\":
            if i + 1 < n and s[i + 1] == "\n":
                i += 2
                continue
            if i + 1 < n:
                cur.append(s[i + 1])
                started = True
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            j = n if j < 0 else j
            cur.append(s[i + 1:j])
            started = True
            i = j + 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n and s[j + 1] in '"\\$`\n':
                    buf.append(s[j + 1])
                    j += 2
                elif s[j] == "$" and s[j + 1:j + 2] == "(":
                    k = _match_close(s, j + 1, "(", ")")
                    buf.append(s[j:k])
                    j = k
                else:
                    buf.append(s[j])
                    j += 1
            cur.append("".join(buf))
            started = True
            i = j + 1
            continue
        if c == "$" and s[i + 1:i + 2] == "(":
            k = _match_close(s, i + 1, "(", ")")
            cur.append(s[i:k])
            started = True
            i = k
            continue
        if c == "$" and s[i + 1:i + 2] == "{":
            k = _match_close(s, i + 1, "{", "}")
            cur.append(s[i:k])
            started = True
            i = k
            continue
        if c == "`":
            j = s.find("`", i + 1)
            j = n if j < 0 else j
            cur.append(s[i:j + 1])
            started = True
            i = j + 1
            continue
        if c in " \t\r":
            end_word()
            i += 1
            continue
        if c == "#" and not started:
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "\n":
            end_word()
            i += 1
            for delim, strip in heredocs:
                while i < n:
                    j = s.find("\n", i)
                    line = s[i:n if j < 0 else j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip else line) == delim:
                        break
            heredocs.clear()
            toks.append(("op", ";"))
            continue
        if c in "<>" or (c == "&" and s[i + 1:i + 2] == ">"):
            if started and "".join(cur).isdigit():  # fd number prefix such as the 2 in 2>&1
                cur, started = [], False
            end_word()
            if c in "<>" and s[i + 1:i + 2] == "(":  # process substitution
                k = _match_close(s, i + 1, "(", ")")
                cur.append(s[i:k])
                started = True
                i = k
                continue
            if c == "&":
                op, i = "&>>" if s[i:i + 3] == "&>>" else "&>", i + (3 if s[i:i + 3] == "&>>" else 2)
            elif s[i:i + 3] == "<<<":
                op, i = "<<<", i + 3
            elif s[i:i + 3] == "<<-":
                op, i = "<<-", i + 3
            elif s[i:i + 2] in ("<<", ">>", ">&", "<&", ">|"):
                op, i = s[i:i + 2], i + 2
            else:
                op, i = c, i + 1
            pending = op
            continue
        if c in ";&|()":
            end_word()
            two = s[i:i + 2]
            if two in ("&&", "||", "|&", ";;"):
                toks.append(("op", two))
                i += 2
            else:
                toks.append(("op", c))
                i += 1
            continue
        cur.append(c)
        started = True
        i += 1
    end_word()
    return toks


def _resolve(cwd, p):
    if not p or "$" in p or "`" in p:
        return None
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def parse_commands(script, cwd, depth=0):
    """Simple commands in order, each with the directory it would run in (cd followed)."""
    cmds, words, redirs, stack = [], [], [], []
    state = {"cwd": cwd}

    def finish():
        nonlocal words, redirs
        w, r = words, redirs
        words, redirs = [], []
        i = 0
        while i < len(w):
            if _ENV_ASSIGN.match(w[i]):
                i += 1
            elif w[i] in _WRAPPERS:
                i += 1
                if w[i - 1] == "env":
                    while i < len(w) and (w[i].startswith("-") or _ENV_ASSIGN.match(w[i])):
                        i += 1
            else:
                break
        w = w[i:]
        if not w and not r:
            return
        cmds.append(Cmd(w, r, state["cwd"]))
        if not w:
            return
        head = os.path.basename(w[0])
        if head == "cd":
            target = _resolve(state["cwd"], w[1] if len(w) > 1 else "~")
            if target:
                state["cwd"] = target
        elif depth < 3 and head in _SHELLS:
            for k, a in enumerate(w[1:], 1):
                if a.startswith("-") and not a.startswith("--") and "c" in a and k + 1 < len(w):
                    cmds.extend(parse_commands(w[k + 1], state["cwd"], depth + 1))
                    break
        elif depth < 3 and head == "eval" and len(w) > 1:
            cmds.extend(parse_commands(" ".join(w[1:]), state["cwd"], depth + 1))

    for t in _tokenize(script):
        if t[0] == "w":
            words.append(t[1])
        elif t[0] == "r":
            redirs.append((t[1], t[2]))
        else:
            finish()
            if t[1] == "(":
                stack.append(state["cwd"])
            elif t[1] == ")" and stack:
                state["cwd"] = stack.pop()
    finish()
    return cmds


def git_invocation(words, cwd):
    """For a `git ...` command return (subcommand, args, cwd after -C), else None."""
    if not words or os.path.basename(words[0]) != "git":
        return None
    i, where = 1, cwd
    while i < len(words):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            where = _resolve(where, words[i + 1]) or where
            i += 2
        elif w in ("-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix") and i + 1 < len(words):
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            return w, words[i + 1:], where
    return None


# ----------------------------------------------------------------------------------
# Transcripts: what did THIS session / agent do?
# ----------------------------------------------------------------------------------

def load_events(path):
    """Ordered events: ("prompt", None, None, None) and ("tool", name, input, cwd)."""
    events = []
    if not path:
        return events
    try:
        fh = open(os.path.expanduser(path), errors="replace")
    except OSError:
        return events
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            msg = d.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if d.get("type") == "user" and not d.get("isMeta"):
                if isinstance(content, str):
                    events.append(("prompt", None, None, None))
                elif isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") != "tool_result" for b in content):
                    events.append(("prompt", None, None, None))
            elif d.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        inp = b.get("input")
                        events.append(("tool", b.get("name", ""), inp if isinstance(inp, dict) else {}, d.get("cwd") or ""))
    return events


def _cmd_changes_files(c, root, cfg, commits=False):
    """Heuristic: does this simple command write or delete files under the repo's code paths?

    Git-ignored paths (run-generated state such as e2e/.auth-state.json) are not code. A commit
    changes no file, so it only counts (commits=True) as evidence that an AGENT did some work.
    """
    def inside(p):
        full = _resolve(c.cwd, p)
        rel = dp.relpath(root, full) if full else None
        if not rel or not dp.is_code_path(rel, cfg):
            return False
        code, _ = dp.run(["git", "check-ignore", "-q", rel], root)
        return code != 0

    for op, target in c.redirects:
        if op.startswith((">", "&>")) and target and target != "/dev/null" and not target.startswith("&") \
                and not target.isdigit() and target != "-" and inside(target):
            return True
    if not c.words:
        return False
    head, args = os.path.basename(c.words[0]), c.words[1:]
    paths = [a for a in args if not a.startswith("-")]
    if head == "sed" and any((a.startswith("-") and not a.startswith("--") and "i" in a) or a.startswith("--in-place") for a in args):
        return any(inside(p) for p in paths)
    if head == "perl" and any(a.startswith("-") and not a.startswith("--") and "i" in a for a in args):
        return any(inside(p) for p in paths)
    if head in ("tee", "cp", "mv", "rm", "touch", "mkdir", "patch", "install", "ln", "truncate", "rsync"):
        return any(inside(p) for p in paths)
    if head == "git" and (args[:1] == ["apply"] or (commits and args[:1] == ["commit"])):
        return True
    if head in ("prettier", "eslint") and any(a in ("--write", "--fix") for a in args):
        return True
    if head in ("npx", "npm", "pnpm", "yarn"):
        if any(a in ("--write", "--fix") for a in args) and any(a in ("prettier", "eslint") for a in args):
            return True
        if len(paths) > 1 and paths[0] in ("install", "i", "uninstall", "remove", "update", "add"):
            return True  # adds or removes a dependency: rewrites package.json
    return False


def edited_code(events, root, cfg, start=0, commits=False):
    """Relative code paths (or "<shell command>") the session changed via tools after events[start:]."""
    hits = []
    for kind, name, inp, cwd in events[start:]:
        if kind != "tool":
            continue
        if name in EDIT_TOOLS:
            rel = dp.relpath(root, inp.get("file_path") or inp.get("notebook_path") or "")
            if rel and dp.is_code_path(rel, cfg):
                hits.append(rel)
        elif name == "Bash":
            for c in parse_commands(str(inp.get("command", "")), cwd or root):
                if _cmd_changes_files(c, root, cfg, commits):
                    hits.append("<shell command>")
                    break
    return hits


def is_test_command(c):
    if not c.words:
        return False
    head, args = os.path.basename(c.words[0]), c.words[1:]
    value_flags = {"-w", "--workspace", "--prefix", "-C", "--cwd", "-F", "--filter"}
    pos, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in value_flags:
            skip = True
        elif not a.startswith("-"):
            pos.append(a)
    if head in ("npm", "pnpm", "yarn", "bun"):
        return bool(pos) and (pos[0] in ("test", "t", "tst") or
                              (pos[0] in ("run", "run-script") and len(pos) > 1 and pos[1].startswith("test")))
    if head == "npx":
        return bool(pos) and pos[0] in ("jest", "vitest", "playwright", "mocha")
    return head in ("jest", "vitest", "playwright", "mocha")


def test_indexes(events):
    out = []
    for idx, (kind, name, inp, cwd) in enumerate(events):
        if kind == "tool" and name == "Bash":
            if any(is_test_command(c) for c in parse_commands(str(inp.get("command", "")), cwd or "/")):
                out.append(idx)
    return out


def impl_re(cfg):
    return re.compile(cfg.get("implPaths") or DEFAULT_IMPL)


def is_impl_path(rel, cfg):
    return bool(impl_re(cfg).search(rel)) and not TEST_PATH_RE.search(rel)


def last_impl_edit(events, root, cfg):
    """Index of the last Edit/Write/MultiEdit of an implementation file in these events, or -1."""
    last = -1
    for idx, (kind, name, inp, cwd) in enumerate(events):
        if kind == "tool" and name in EDIT_TOOLS:
            rel = dp.relpath(root, inp.get("file_path") or "")
            if rel and is_impl_path(rel, cfg):
                last = idx
    return last


def own_impl_edits(events, root, cfg):
    """Implementation files this transcript edited with Edit/Write/MultiEdit, in first-edit order."""
    seen = []
    for kind, name, inp, cwd in events:
        if kind == "tool" and name in EDIT_TOOLS:
            rel = dp.relpath(root, inp.get("file_path") or "")
            if rel and is_impl_path(rel, cfg) and rel not in seen:
                seen.append(rel)
    return seen


def tests_missing(events, root, cfg, impl_changed, ordered):
    """True when implementation code changed and no test command is on record.

    ordered=True (we know which edits this transcript made): a test command must come after
    the last implementation edit. ordered=False (the gates, which judge a diff made by
    someone else): any test command anywhere in the transcript satisfies it.
    """
    if not impl_changed:
        return False
    tests = test_indexes(events)
    last_edit = last_impl_edit(events, root, cfg) if ordered else -1
    if last_edit < 0:
        return not tests
    return not any(t > last_edit for t in tests)


def transcript_for(payload):
    """The transcript of whoever is acting: the subagent's own when fired inside one."""
    tp = os.path.expanduser(payload.get("transcript_path") or "")
    aid = payload.get("agent_id")
    if aid and tp.endswith(".jsonl"):
        cand = f"{tp[:-6]}/subagents/agent-{aid}.jsonl"
        if os.path.exists(cand):
            return cand
    return tp if tp and os.path.exists(tp) else ""


# ----------------------------------------------------------------------------------
# Repository state helpers
# ----------------------------------------------------------------------------------

def wired(root):
    return bool(root) and os.path.exists(os.path.join(root, ".claude", "dev-policy.json"))


def current_branch(root):
    code, out = dp.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], root)
    return out.strip() if code == 0 else ""


def is_ancestor(root, ref, of="HEAD"):
    code, _ = dp.run(["git", "merge-base", "--is-ancestor", ref, of], root)
    return code == 0


def worktrees(root):
    """[{path, branch, locked, lock_reason}] from `git worktree list --porcelain`."""
    code, out = dp.run(["git", "worktree", "list", "--porcelain"], root)
    if code != 0:
        return []
    items, cur = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[9:], "branch": "", "locked": False, "lock_reason": ""}
            items.append(cur)
        elif cur is not None and line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "", 1)
        elif cur is not None and line.startswith("locked"):
            cur["locked"] = True
            cur["lock_reason"] = line[6:].strip()
    return items


def worktree_of_branch(root, branch):
    for w in worktrees(root):
        if w["branch"] == branch:
            return w["path"]
    return ""


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _is_check_shell(task, root):
    """A backgrounded shell task that is running tests or check.py: its result is the check.

    Blocking the reply while it runs only asks for the same check a second time. Any other
    shell task (a log tail, a dev server) is not work in progress and never silences the hook.
    """
    if task.get("type") != "shell":
        return False
    cmd = str(task.get("command") or "")
    if "dev-policy/scripts/check.py" in cmd:
        return True
    return any(is_test_command(c) for c in parse_commands(cmd, root))


def agents_running(payload, root):
    """True when background agents may still be changing the repository.

    The Stop payload's background_tasks list (documented: present when the task registry
    is reachable) is authoritative when it is there. Without it, any locked worktree under
    .claude/worktrees whose recorded process is alive counts.
    """
    tasks = payload.get("background_tasks")
    if isinstance(tasks, list):
        return any(isinstance(t, dict) and str(t.get("status", "running")).lower() not in TERMINAL_STATUSES
                   and (t.get("type") in AGENT_TASK_TYPES or _is_check_shell(t, root)) for t in tasks)
    for w in worktrees(root):
        if not w["locked"] or f"/{dp.WORKTREES_PREFIX}" not in w["path"] + "/":
            continue
        m = re.search(r"\bpid (\d+)", w["lock_reason"])
        if not m or _pid_alive(int(m.group(1))):
            return True
    return False


def hygiene_must_fix(root):
    script = os.path.join(root, ".claude", "hooks", "repo-hygiene.sh")
    if not os.path.exists(script):
        return []
    code, out = dp.run(["bash", script, "must-fix"], root, timeout=20)
    return [l.strip() for l in out.splitlines() if l.strip()] if code == 0 else []


def memo_path(root):
    return os.path.join(dp.git_common_dir(root), "dev-policy-reported.json")


def memo_get(root, key):
    try:
        with open(memo_path(root)) as fh:
            return json.load(fh).get(key)
    except Exception:
        return None


def memo_set(root, key, value):
    try:
        try:
            with open(memo_path(root)) as fh:
                data = json.load(fh)
        except Exception:
            data = {}
        data[key] = value
        if len(data) > 200:
            data = dict(list(data.items())[-200:])
        with open(memo_path(root), "w") as fh:
            json.dump(data, fh)
    except OSError:
        pass


def signature(*parts):
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8", "replace")).hexdigest()


# ----------------------------------------------------------------------------------
# Gate messages (plain English; they are shown to the agent and the owner)
# ----------------------------------------------------------------------------------

def stamp_problem(root, tree, label):
    """None when check.py has PASSED on this exact committed tree, else why not."""
    st = dp.lookup_tree_stamp(root, tree)
    if dp.passing(st):
        return None
    if st is None:
        return (f"the development-policy check has not been run on the exact code of {label} "
                f"(git tree {tree[:10]}), or it was run with uncommitted changes in the way")
    if st.get("status") == "pass":
        return f"the only check on record for {label} was a partial run (type check or lint skipped)"
    fails = st.get("failures") or ["(no detail recorded)"]
    return f"the development-policy check FAILED on {label}: " + " ; ".join(fails)


def how_to_unlock(root, branch):
    where = worktree_of_branch(root, branch) if branch else ""
    place = f"go to the worktree where it lives ({where})" if where and where != root else f"check out '{branch}'" if branch else "check out that code"
    return (f"To unlock: {place}, make sure the working tree is clean (commit everything), run `{CHECK_CMD}`, "
            f"fix every FAIL, commit the fixes and run it again until it says PASS, then retry this command.")


def deny_text(problems, unlock):
    lines = ["Blocked by the development-policy gate (code is about to leave the working checkout):"]
    lines += [f"- {p}" for p in problems]
    if unlock:
        lines.append(unlock)
    return "\n".join(lines)


# ----------------------------------------------------------------------------------
# The three Bash gates
# ----------------------------------------------------------------------------------

def _tests_problem(payload, root, cfg, files):
    tp = transcript_for(payload)
    if not tp:
        return None
    if not any(is_impl_path(f, cfg) for f in files):
        return None
    if tests_missing(load_events(tp), root, cfg, True, False):
        return ("implementation code changed (" + ", ".join([f for f in files if is_impl_path(f, cfg)][:3]) +
                ") but no test command (npm test, jest, vitest, playwright) is on record in this session; run the test suites first")
    return None


def gate_merge(args, cwd, payload, sim_branch):
    root = dp.repo_root(cwd)
    if not wired(root):
        return []
    branch = sim_branch.get(root) or current_branch(root)
    if branch not in MAIN_BRANCHES:
        return []
    head_ref = branch if root in sim_branch else "HEAD"  # an earlier `git checkout main` in the same command line
    if any(a in ("--abort", "--continue", "--quit") for a in args):
        return []
    refs, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in ("-m", "-F", "-s", "-X", "--file", "--strategy", "--strategy-option", "--into-name"):
            skip = True
        elif not a.startswith("-"):
            refs.append(a)
    cfg = dp.load_config(root)
    problems, unlock_branch = [], ""
    for ref in refs:
        tree = dp.tree_of(root, ref)
        if not tree or is_ancestor(root, ref, head_ref):
            continue  # unknown ref (git itself will complain) or nothing to merge
        code, base = dp.run(["git", "merge-base", head_ref, ref], root)
        files = dp.code_files_between(root, cfg, base.strip(), ref) if code == 0 else []
        if code == 0 and not files:
            continue  # nothing the check looks at differs
        why = stamp_problem(root, tree, f"'{ref}'")
        if why:
            problems.append(f"merging '{ref}' into {branch}: {why}")
            unlock_branch = unlock_branch or ref
        t = _tests_problem(payload, root, cfg, files)
        if t:
            problems.append(f"merging '{ref}' into {branch}: {t}")
    return problems and [deny_text(problems, how_to_unlock(root, unlock_branch))]


def push_problems(root, tips):
    """tips: [(label, sha-or-ref)] -> (problems, files-changed-union)."""
    cfg = dp.load_config(root)
    problems, allfiles, first = [], [], ""
    for label, ref in tips:
        tree = dp.tree_of(root, ref)
        if not tree:
            continue
        files = dp.code_files_between(root, cfg, dp.merge_base_for(root, ref), ref)
        if not files:
            continue
        allfiles += files
        why = stamp_problem(root, tree, label)
        if why:
            problems.append(f"pushing {label}: {why}")
            first = first or label
    return problems, allfiles, first


def gate_push(args, cwd, payload):
    root = dp.repo_root(cwd)
    if not wired(root):
        return []
    flags = [a for a in args if a.startswith("-")]
    if any(f in ("-n", "--dry-run", "-d", "--delete") or f.startswith("--delete") for f in flags):
        return []
    positional, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
            skip = True
        elif not a.startswith("-"):
            positional.append(a)
    refspecs = positional[1:]
    tips = []
    if not refspecs or "--all" in flags or "--mirror" in flags:
        tips.append((current_branch(root) or "HEAD", "HEAD"))
    for rs in refspecs:
        src = rs.lstrip("+").split(":")[0]
        if not src or src.startswith("refs/tags/") or rs.startswith(":"):
            continue
        tips.append((src, src))
    problems, files, first = push_problems(root, tips)
    cfg = dp.load_config(root)
    t = _tests_problem(payload, root, cfg, files)
    if t:
        problems.append(f"pushing: {t}")
    return problems and [deny_text(problems, how_to_unlock(root, first if first not in ("HEAD", "") else current_branch(root)))]


def _is_deploy(words):
    if not words:
        return None
    head = os.path.basename(words[0])
    if head == "deploy-test.sh":
        return words[0]
    if head in _SHELLS and "-n" not in words[1:]:  # -n = syntax check only
        for a in words[1:]:
            if not a.startswith("-"):
                return a if os.path.basename(a) == "deploy-test.sh" else None
    return None


def gate_deploy(script, cwd, payload):
    path = _resolve(cwd, script) or os.path.join(cwd, script)
    root = dp.repo_root(os.path.dirname(path) if os.path.isdir(os.path.dirname(path)) else cwd)
    if not wired(root):
        return []
    cfg = dp.load_config(root)
    problems, need_check = [], False
    if not dp.is_clean(root):
        code, out = dp.run(["git", "status", "--porcelain", "--", ".", f":(exclude){dp.WORKTREES_PREFIX.rstrip('/')}"], root)
        sample = ", ".join(l[3:] for l in out.splitlines()[:4])
        problems.append("the working tree has uncommitted changes (" + sample + "). The deploy uploads the working tree, "
                        "so what ships would not be the code the check approved. Commit or discard them")
    tree = dp.head_tree(root)
    head_files = dp.code_files_between(root, cfg, dp.merge_base_for(root, "HEAD"), "HEAD")
    if head_files:
        why = stamp_problem(root, tree, "HEAD")
        if why:
            problems.append(f"deploying: {why}")
            need_check = True
    wt_dir = os.path.join(root, ".claude", "worktrees")
    extra = set()
    if os.path.isdir(wt_dir):
        extra |= {e for e in os.listdir(wt_dir) if not e.startswith(".")}
    for w in worktrees(root):
        if f"/{dp.WORKTREES_PREFIX}" in w["path"] + "/" and os.path.realpath(w["path"]) != os.path.realpath(root):
            extra.add(os.path.basename(w["path"]))
    if extra:
        names = ", ".join(sorted(extra)[:5]) + (" ..." if len(extra) > 5 else "")
        problems.append(f"{len(extra)} agent worktree(s) still exist under .claude/worktrees ({names}). They hold full copies of the "
                        "source and run-generated login state and must not be near an upload. If agents are still running, wait for them; "
                        "otherwise remove each with `git worktree remove <path>`")
    t = _tests_problem(payload, root, cfg, head_files)
    if t:
        problems.append(f"deploying: {t}")
    return problems and [deny_text(problems, how_to_unlock(root, current_branch(root)) if need_check else "")]


_QUICK = re.compile(r"\b(merge|push)\b|deploy-test")


def evaluate_bash(payload):
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not _QUICK.search(cmd):
        return []
    cwd = payload.get("cwd") or os.getcwd()
    out, sim = [], {}
    for c in parse_commands(cmd, cwd):
        gi = git_invocation(c.words, c.cwd)
        if gi:
            sub, args, where = gi
            if sub in ("checkout", "switch"):
                names = [a for a in args if not a.startswith("-")]
                if names and "--" not in args:
                    sim[dp.repo_root(where)] = names[0]
            elif sub == "merge":
                out += gate_merge(args, where, payload, sim)
            elif sub == "push":
                out += gate_push(args, where, payload)
            continue
        script = _is_deploy(c.words)
        if script:
            out += gate_deploy(script, c.cwd, payload)
    seen, uniq = set(), []
    for m in out:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


# ----------------------------------------------------------------------------------
# Agent self-check (SubagentStop, and PreToolUse on SubagentHandback)
# ----------------------------------------------------------------------------------

def agent_context(payload):
    """(agent transcript path, directory the agent worked in)."""
    tp = os.path.expanduser(payload.get("agent_transcript_path") or "")
    if not tp:
        base = os.path.expanduser(payload.get("transcript_path") or "")
        aid = payload.get("agent_id")
        tp = f"{base[:-6]}/subagents/agent-{aid}.jsonl" if aid and base.endswith(".jsonl") else ""
    cwd = ""
    if tp.endswith(".jsonl"):
        try:
            with open(tp[:-6] + ".meta.json") as fh:
                wt = json.load(fh).get("worktreePath") or ""
            if wt and os.path.isdir(wt):
                cwd = wt
        except Exception:
            pass
    if not cwd and tp and os.path.exists(tp):
        last = ""
        try:
            with open(tp, errors="replace") as fh:
                for line in fh:
                    m = re.search(r'"cwd":\s*"([^"]+)"', line)
                    if m:
                        last = m.group(1)
        except OSError:
            pass
        if last and os.path.isdir(last):
            cwd = last
    return (tp if tp and os.path.exists(tp) else ""), cwd or payload.get("cwd") or os.getcwd()


def run_check(root):
    """Run check.py unless this exact state already passed. Returns (status, failures, fingerprint)."""
    cfg = dp.load_config(root)
    fp, _ = dp.fingerprint(root, cfg)
    st = dp.read_stamp(root)
    if st and st.get("fingerprint") == fp and st.get("complete", True) and st.get("status") in ("pass", "fail"):
        return st["status"], st.get("failures") or [], fp
    dp.run([sys.executable, CHECK_SCRIPT], root, timeout=CHECK_TIMEOUT)
    st = dp.read_stamp(root) or {}
    return st.get("status", "fail"), st.get("failures") or ["check.py did not complete (see its output)"], fp


def subagent_self_check(payload):
    """Reason text to hand back to the agent, or None. Blocks at most once per agent."""
    aid = payload.get("agent_id") or ""
    tp, cwd = agent_context(payload)
    root = dp.repo_root(cwd)
    if not wired(root) or not aid:
        return None
    if memo_get(root, f"agent:{aid}"):
        return None  # already told once: let it report
    cfg = dp.load_config(root)
    events = load_events(tp) if tp else []
    if tp and not edited_code(events, root, cfg, 0, commits=True):
        return None  # read-only agent (nothing it did touched code paths)
    base, changed = dp.changed_files(root, cfg)
    if not changed:
        return None
    status, failures, fp = run_check(root)
    problems = []
    if status != "pass":
        problems += [f"the policy check FAILED: {f}" for f in failures]
    # Tests are owed for the implementation files THIS agent edited (from its transcript),
    # not for every implementation file on the branch: an agent fixing one doc line on a
    # branch other agents built was told to run tests for code it never touched.
    impl = own_impl_edits(events, root, cfg)
    if events and tests_missing(events, root, cfg, bool(impl), True):
        problems.append("you changed implementation code (" + ", ".join(impl[:3]) + ") but no test command is on record after your last edit; run the relevant test suites")
    if not problems:
        return None
    memo_set(root, f"agent:{aid}", signature(fp, *problems))
    return ("Before you hand back: the development-policy self-check found problems in the code in your working directory.\n" +
            "\n".join(f"- {p}" for p in problems) +
            f"\nFix them, re-run `{CHECK_CMD}` until it says PASS, run the tests, then report. This check will not ask again: "
            "if a failure is not yours to fix (for example it comes from files you were told not to touch), say so plainly in your report.")


# ----------------------------------------------------------------------------------
# Stop (main session, end of every reply): quiet unless all conditions hold
# ----------------------------------------------------------------------------------

def stop_reason(payload):
    root = dp.repo_root(payload.get("cwd"))
    if not root:
        return None
    tp = os.path.expanduser(payload.get("transcript_path") or "")
    events = load_events(tp)
    if not events:
        return None
    cfg = dp.load_config(root)
    last_prompt = max((i for i, e in enumerate(events) if e[0] == "prompt"), default=-1)
    if not edited_code(events, root, cfg, last_prompt + 1):
        return None  # (a) the main session did not edit code this turn
    if agents_running(payload, root):
        return None  # (b) agents are still working; the gates and the agent self-check cover them
    problems = []
    fp, changed = dp.fingerprint(root, cfg)
    if fp:
        st = dp.read_stamp(root)
        if st and st.get("fingerprint") == fp and st.get("status") == "fail":
            problems.append(f"the last policy check on this code FAILED: " + " ; ".join(st.get("failures") or ["see its output"]))
        elif not (st and st.get("fingerprint") == fp and st.get("status") == "pass"):
            problems.append(f"{len(changed)} code file(s) changed since the last passing policy check")
    if tests_missing(events, root, cfg, last_impl_edit(events, root, cfg) >= 0, True):
        problems.append("you edited implementation code but no test command is on record after your last edit")
    problems += [f"repo hygiene: {h}" for h in hygiene_must_fix(root)]
    if not problems:
        return None
    sig = signature(fp, *problems)
    key = f"stop:{payload.get('session_id') or 'nosession'}"
    if memo_get(root, key) == sig:
        return None  # this exact state was already reported; never loop on it
    memo_set(root, key, sig)
    return ("You edited code in this reply and it is not ready to leave your hands:\n" +
            "\n".join(f"- {p}" for p in problems) +
            f"\nRun `{CHECK_CMD}`, fix every FAIL, run the test suites, resolve any hygiene item, then stop. "
            "If something cannot be fixed, tell the owner plainly why.")


# ----------------------------------------------------------------------------------
# Entry points
# ----------------------------------------------------------------------------------

def _read_payload():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))


def mode_pre_push(argv):
    """git pre-push: stdin lines `<local ref> <local sha> <remote ref> <remote sha>`."""
    root = dp.repo_root(os.getcwd())
    if not wired(root):
        return 0
    zeros = set("0")
    tips = []
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) >= 2 and not set(parts[1]) <= zeros:
            tips.append((parts[0].replace("refs/heads/", "", 1), parts[1]))
    problems, _, first = push_problems(root, tips)
    if not problems:
        return 0
    sys.stderr.write(deny_text(problems, how_to_unlock(root, first if first not in ("HEAD", "") else current_branch(root))) +
                     "\n(bypass deliberately with `git push --no-verify`)\n")
    return 1


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "pre-push":
        try:
            return mode_pre_push(sys.argv[2:])
        except Exception:
            if os.environ.get("DEV_POLICY_DEBUG"):
                traceback.print_exc()
            return 0
    payload = _read_payload()
    try:
        if mode == "pre-bash":
            msgs = evaluate_bash(payload)
            if msgs:
                _deny("\n".join(msgs))
        elif mode == "pre-handback":
            reason = subagent_self_check(payload)
            if reason:
                _deny(reason)
        elif mode == "subagent-stop":
            reason = subagent_self_check(payload)
            if reason:
                print(json.dumps({"decision": "block", "reason": reason}))
        elif mode == "stop":
            reason = stop_reason(payload)
            if reason:
                print(json.dumps({"decision": "block", "reason": reason}))
    except Exception:
        if os.environ.get("DEV_POLICY_DEBUG"):
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
