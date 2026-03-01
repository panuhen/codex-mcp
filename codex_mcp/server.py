"""MCP server that exposes Codex CLI as tools for Claude Code."""

import argparse
import asyncio
import json
import os
import shutil

from mcp.server.fastmcp import FastMCP

TIMEOUT_SECONDS = 300  # 5 minutes

mcp = FastMCP(
    "codex",
    instructions="Run Codex CLI headlessly — code review, security audits, brainstorming, and more.",
)

# Server-wide defaults, set via CLI args or env vars in main().
_default_profile: str = ""
_default_config_overrides: list[str] = []


def _find_codex() -> str:
    """Find the codex binary on PATH."""
    path = shutil.which("codex")
    if path is None:
        raise RuntimeError(
            "codex CLI not found on PATH. Install it first: https://github.com/openai/codex"
        )
    return path


async def _run_codex(
    args: list[str],
    *,
    cwd: str | None = None,
    timeout: int = TIMEOUT_SECONDS,
    profile: str = "",
) -> dict:
    """Run codex with the given args, parse JSONL output, return structured result."""
    codex = _find_codex()

    # Build top-level flags (before the subcommand).
    prefix: list[str] = []
    effective_profile = profile or _default_profile
    if effective_profile:
        prefix.extend(["-p", effective_profile])
    for override in _default_config_overrides:
        prefix.extend(["-c", override])

    proc = await asyncio.create_subprocess_exec(
        codex,
        *prefix,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"error": f"Codex timed out after {timeout}s", "session_id": None}

    return _parse_jsonl(
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
        proc.returncode or 0,
    )


def _parse_jsonl(stdout: str, stderr: str, returncode: int) -> dict:
    """Parse Codex JSONL output into a structured result."""
    session_id = None
    text_parts: list[str] = []

    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")

        if event_type == "thread.started":
            session_id = event.get("thread_id")
        elif event_type == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                text = item.get("text", "")
                if text:
                    text_parts.append(text)

    if returncode != 0 and not text_parts:
        return {
            "error": f"Codex exited with code {returncode}: {stderr.strip()}",
            "session_id": session_id,
        }

    return {
        "text": "\n\n".join(text_parts),
        "session_id": session_id,
    }


def _exec_args(
    prompt: str,
    *,
    sandbox: str | None = None,
    model: str | None = None,
) -> list[str]:
    """Build args for `codex exec <prompt>`."""
    args: list[str] = ["exec", "--json"]
    if sandbox:
        args.extend(["-s", sandbox])
    if model:
        args.extend(["-m", model])
    args.append(prompt)
    return args


def _resume_args(session_id: str, prompt: str) -> list[str]:
    """Build args for `codex exec resume <session_id> <prompt>`."""
    return ["exec", "resume", "--json", session_id, prompt]


def _review_args(
    *,
    prompt: str = "",
    base: str = "",
    uncommitted: bool = False,
    commit: str = "",
) -> list[str]:
    """Build args for `codex exec review`."""
    args: list[str] = ["exec", "review", "--json"]
    if base:
        args.extend(["--base", base])
    if uncommitted or (not base and not commit):
        args.append("--uncommitted")
    if commit:
        args.extend(["--commit", commit])
    if prompt:
        args.append(prompt)
    return args


# ---------- Tool 1: codex_exec ----------


@mcp.tool()
async def codex_exec(
    prompt: str,
    working_dir: str = "",
    model: str = "",
    sandbox: str = "read-only",
    session_id: str = "",
) -> str:
    """Run Codex headlessly with a prompt.

    Args:
        prompt: The instruction/prompt for Codex.
        working_dir: Working directory for Codex (defaults to its own cwd).
        model: Model to use (e.g. "o3", "o4-mini"). Defaults to codex config.
        sandbox: Sandbox mode: "read-only" or "workspace-write". Default "read-only".
        session_id: Resume a previous session. Omit to start fresh.
    """
    cwd = working_dir or None
    if session_id:
        args = _resume_args(session_id, prompt)
    else:
        args = _exec_args(prompt, sandbox=sandbox or "read-only", model=model or None)
    result = await _run_codex(args, cwd=cwd)
    return json.dumps(result, indent=2)


# ---------- Tool 2: codex_ask ----------


@mcp.tool()
async def codex_ask(
    prompt: str,
    working_dir: str = "",
    model: str = "",
    session_id: str = "",
) -> str:
    """Read-only question/analysis via Codex. Always uses read-only sandbox.

    Use for explanations, architecture questions, code understanding, analysis.

    Args:
        prompt: Your question or analysis request.
        working_dir: Working directory for Codex.
        model: Model to use. Defaults to codex config.
        session_id: Resume a previous session.
    """
    cwd = working_dir or None
    if session_id:
        args = _resume_args(session_id, prompt)
    else:
        args = _exec_args(prompt, sandbox="read-only", model=model or None)
    result = await _run_codex(args, cwd=cwd)
    return json.dumps(result, indent=2)


# ---------- Tool 3: codex_review ----------


@mcp.tool()
async def codex_review(
    prompt: str = "",
    working_dir: str = "",
    base: str = "",
    uncommitted: bool = False,
    commit: str = "",
    session_id: str = "",
) -> str:
    """Code review via Codex.

    Runs `codex exec review` against a git repository. Specify what to review
    with base, uncommitted, or commit. At least one of these should be provided
    (defaults to uncommitted if none given).

    Args:
        prompt: Custom review instructions (optional).
        working_dir: Git repository directory.
        base: Review changes against this base branch (e.g. "main").
        uncommitted: If true, review staged/unstaged/untracked changes.
        commit: Review changes introduced by this commit SHA.
        session_id: Resume a previous review session.
    """
    cwd = working_dir or None
    if session_id:
        args = _resume_args(session_id, prompt or "Continue the review.")
    else:
        args = _review_args(prompt=prompt, base=base, uncommitted=uncommitted, commit=commit)
    result = await _run_codex(args, cwd=cwd)
    return json.dumps(result, indent=2)


# ---------- Tool 4: codex_security_audit ----------

_SECURITY_PROMPT = """\
Perform a thorough security audit of this codebase. Focus on:

1. OWASP Top 10 vulnerabilities
2. Injection flaws (SQL, command, XSS, SSTI, path traversal)
3. Authentication and authorization weaknesses
4. Secrets, credentials, or API keys in code or config
5. Cryptographic issues (weak algorithms, hardcoded keys, poor randomness)
6. Insecure dependencies or known CVEs
7. Input validation and sanitization gaps
8. Insecure deserialization
9. CORS, CSRF, and header security misconfigurations
10. Logging and error handling that leaks sensitive data

{focus_section}
{files_section}

For each finding, provide:
- Severity (Critical / High / Medium / Low / Info)
- Location (file and line if possible)
- Description of the vulnerability
- Recommended fix
"""


@mcp.tool()
async def codex_security_audit(
    working_dir: str = "",
    focus: str = "",
    files: list[str] | None = None,
    session_id: str = "",
) -> str:
    """Security-focused code audit via Codex.

    Runs a comprehensive security review based on OWASP Top 10, injection,
    auth/authz, secrets, crypto, and dependency analysis.

    Args:
        working_dir: Directory to audit.
        focus: Specific focus area (e.g. "auth", "API", "input validation").
        files: Specific files to audit. If empty, audits the whole project.
        session_id: Resume a previous audit session.
    """
    focus_section = f"Pay special attention to: {focus}" if focus else ""
    files_section = (
        f"Focus specifically on these files: {', '.join(files)}" if files else ""
    )
    prompt = _SECURITY_PROMPT.format(
        focus_section=focus_section, files_section=files_section
    ).strip()

    cwd = working_dir or None
    if session_id:
        args = _resume_args(session_id, prompt)
    else:
        args = _exec_args(prompt, sandbox="read-only")
    result = await _run_codex(args, cwd=cwd)
    return json.dumps(result, indent=2)


# ---------- Tool 5: codex_brainstorm ----------

_BRAINSTORM_PROMPT = """\
Brainstorm about the following topic: {topic}

{context_section}

Explore this from multiple perspectives:
1. List at least 3 distinct approaches or solutions
2. For each approach, analyze trade-offs, pros, and cons
3. Consider edge cases, scalability, and maintainability
4. Recommend the best option with clear rationale
5. If relevant, suggest a rough implementation plan

Be creative but practical. Ground suggestions in real-world engineering constraints.
"""


@mcp.tool()
async def codex_brainstorm(
    topic: str,
    context: str = "",
    working_dir: str = "",
    model: str = "",
    session_id: str = "",
) -> str:
    """Multi-perspective design exploration via Codex.

    Explores multiple approaches to a topic with trade-offs and recommendations.

    Args:
        topic: What to brainstorm about.
        context: Background info, constraints, current approach (optional).
        working_dir: Working directory for code context.
        model: Model to use. Defaults to codex config.
        session_id: Resume a previous brainstorm session.
    """
    context_section = f"Context and constraints:\n{context}" if context else ""
    prompt = _BRAINSTORM_PROMPT.format(
        topic=topic, context_section=context_section
    ).strip()

    cwd = working_dir or None
    if session_id:
        args = _resume_args(session_id, prompt)
    else:
        args = _exec_args(prompt, sandbox="read-only", model=model or None)
    result = await _run_codex(args, cwd=cwd)
    return json.dumps(result, indent=2)


# ---------- Tool 6: codex_resume ----------


@mcp.tool()
async def codex_resume(
    session_id: str,
    prompt: str,
    working_dir: str = "",
) -> str:
    """Continue any previous Codex session.

    Standalone resume when you just want to continue a conversation
    without a specific tool's framing.

    Args:
        session_id: The session ID from a previous call (required).
        prompt: Follow-up message to send (required).
        working_dir: Working directory for Codex.
    """
    cwd = working_dir or None
    args = _resume_args(session_id, prompt)
    result = await _run_codex(args, cwd=cwd)
    return json.dumps(result, indent=2)


def main():
    """Entry point for the codex-mcp server."""
    global _default_profile, _default_config_overrides

    parser = argparse.ArgumentParser(description="Codex MCP server")
    parser.add_argument(
        "-p", "--profile",
        default=os.environ.get("CODEX_PROFILE", ""),
        help="Default Codex config profile (e.g. 'azure'). "
             "Can also be set via CODEX_PROFILE env var.",
    )
    parser.add_argument(
        "-c", "--config",
        action="append",
        default=[],
        help="Codex config override (key=value), passed as -c to codex. Repeatable.",
    )
    args = parser.parse_args()

    _default_profile = args.profile
    _default_config_overrides = args.config

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
