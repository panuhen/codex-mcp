# codex-mcp

MCP server that exposes the [OpenAI Codex CLI](https://github.com/openai/codex) as tools for Claude Code.

## Tools

| Tool | Description |
|------|-------------|
| `codex_exec` | Run Codex with any prompt |
| `codex_ask` | Read-only questions and code analysis |
| `codex_review` | Code review against a branch, commit, or uncommitted changes |
| `codex_security_audit` | OWASP-based security audit |
| `codex_brainstorm` | Multi-perspective design exploration |
| `codex_resume` | Continue any previous Codex session |

## Prerequisites

- Python 3.11+
- [Codex CLI](https://github.com/openai/codex) installed and on your PATH

## Install

```bash
git clone https://github.com/panuhen/codex-mcp.git
cd codex-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configure in Claude Code

Add to your Claude Code MCP settings (`~/.mcp.json` or project-level `.mcp.json`):

```json
{
  "mcpServers": {
    "codex": {
      "command": "/absolute/path/to/codex-mcp/.venv/bin/codex-mcp"
    }
  }
}
```

Replace `/absolute/path/to/codex-mcp` with the actual path where you cloned the repo.

### Using a Codex profile (e.g. Azure OpenAI)

If you have a profile configured in `~/.codex/config.toml` (e.g. an `azure` profile with a custom model provider), pass `--profile` via `args` and supply the required API key via `env`:

```json
{
  "mcpServers": {
    "codex": {
      "command": "/absolute/path/to/codex-mcp/.venv/bin/codex-mcp",
      "args": ["--profile", "azure"],
      "env": {
        "AZURE_OPENAI_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

You can also set the profile via the `CODEX_PROFILE` environment variable instead of `args`.

Additional codex config overrides can be passed with `-c`:

```json
{
  "mcpServers": {
    "codex": {
      "command": "/absolute/path/to/codex-mcp/.venv/bin/codex-mcp",
      "args": ["--profile", "azure", "-c", "model=\"o3\""]
    }
  }
}
```

Restart Claude Code and the Codex tools will be available.

## Usage examples

Once configured, Claude Code can use the tools directly:

- *"Review my uncommitted changes"* — triggers `codex_review`
- *"Run a security audit on src/"* — triggers `codex_security_audit`
- *"Brainstorm approaches for caching"* — triggers `codex_brainstorm`
- *"Ask Codex how the auth module works"* — triggers `codex_ask`

Sessions can be continued with `codex_resume` using the `session_id` returned by any tool.

## License

MIT
