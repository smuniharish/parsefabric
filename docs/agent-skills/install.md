# Install the skills

## With the skills CLI

The [skills CLI](https://github.com/vercel-labs/skills) finds both skills
through the repository's `skills.sh.json`:

```bash
npx skills add smuniharish/parsefabric                                 # both skills
npx skills add smuniharish/parsefabric --skill parsefabric             # one skill
npx skills add smuniharish/parsefabric --skill parsefabric-extend
```

Follow the CLI's prompts to choose your agent, then check that it placed a
folder for each skill in that agent's skills directory.

## Manually

Copy the complete skill directory, including `SKILL.md`, from
[`parsefabric-skills/skills/`](https://github.com/smuniharish/parsefabric/tree/main/parsefabric-skills/skills)
into the location your agent reads. The tables below use `parsefabric`;
install `parsefabric-extend` the same way.

### Claude Code

| Scope | Destination |
| --- | --- |
| Current repository | `.claude/skills/parsefabric/` |
| All local projects | `~/.claude/skills/parsefabric/` |

Restart Claude Code after copying. Claude selects the skill when a task
matches its description, or you can invoke it with `/parsefabric`. See
[Claude Code skills](https://code.claude.com/docs/en/skills).

### Codex

| Scope | Destination |
| --- | --- |
| Current repository | `.agents/skills/parsefabric/` |
| All local projects | `~/.agents/skills/parsefabric/` |

Codex picks up new skills automatically; restart it if the skill does not
appear. Invoke it with `$parsefabric`, or list skills with `/skills`.

### Cursor

| Scope | Destination |
| --- | --- |
| Current repository | `.agents/skills/parsefabric/` or `.cursor/skills/parsefabric/` |
| All local projects | `~/.agents/skills/parsefabric/` or `~/.cursor/skills/parsefabric/` |

Restart Cursor after copying. In Agent chat, type `/` and select the skill,
or let Cursor activate it from its description. See
[Cursor Agent Skills](https://cursor.com/docs/skills).

### GitHub Copilot

| Scope | Destination |
| --- | --- |
| Current repository | `.agents/skills/parsefabric/`, `.github/skills/parsefabric/` or `.claude/skills/parsefabric/` |
| All local projects | `~/.agents/skills/parsefabric/` or `~/.copilot/skills/parsefabric/` |

In Copilot CLI, start a new session or run `/skills reload`, then check the
skill with `/skills info parsefabric`. See
[adding agent skills for GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills).

### Other agents

Copy the skill folder into the skills directory your agent documents. No
adapter is needed: every Agent Skills host reads the same files.

## Skills from dependencies and integrations

These are maintained by their respective projects, installed separately from
ParseFabric, and optional. Review their instructions and compatibility with
your installed versions before use.

### Tree-sitter language pack

The [language-pack skills](https://github.com/xberg-io/tree-sitter-language-pack/tree/main/skills)
cover code detection, parsing and parser-cache management. Install the main
`tree-sitter-language-pack` skill with the skills CLI:

```bash
npx skills add xberg-io/tree-sitter-language-pack --skill tree-sitter-language-pack
```

The project's [installation guide](https://github.com/xberg-io/tree-sitter-language-pack/blob/main/plugin/README.md)
also lists its focused skills and optional plugin. Node.js and the skills CLI
are needed for the command above; use the installed language-pack version's
documentation for its Python API and grammar cache.

### Pydantic

The standalone [`pydantic` skill](https://github.com/pydantic/skills/tree/main/skills/pydantic)
covers validation and serialization. For Claude Code, install the upstream
plugin:

```bash
claude plugin marketplace add pydantic/skills
claude plugin install pydantic@pydantic-skills
```

For another supported agent, copy the complete `skills/pydantic/` directory
from the [Pydantic skills repository](https://github.com/pydantic/skills)
into that agent's skills directory.

### uv and Ruff

The [Astral plugin](https://github.com/astral-sh/agent-plugins) supplies
`uv`, `ruff` and `ty` skills for Python tooling. For Codex, install it with:

```bash
codex plugin marketplace add astral-sh/agent-plugins
codex plugin add astral@astral-sh
```

The upstream guide also documents Claude Code installation. The `ty` skill
is optional; ParseFabric uses Pyrefly for its own type checks.

### LangChain and LangGraph

The [LangChain skills repository](https://github.com/langchain-ai/langchain-skills)
provides `langchain-build-agent`, `langchain-agent-tracing`,
`langchain-agent-monitoring`, and `langchain-eval-engineering`. To install
its current skills for a supported agent:

```bash
npx skills add langchain-ai/langchain-skills --skill '*' --yes
```

Installing these skills does not install the optional ParseFabric
`langchain` extra or LangGraph. Install those separately only when needed;
see [LangChain and LangGraph](../integrations/langchain.md). The skills-only
installation does not register the upstream documentation MCP servers.

### Streamlit

The optional Streamlit playground can use Streamlit's bundled
`developing-with-streamlit` skill. Install Streamlit in your project
environment, then run:

```bash
streamlit skills
```

The [Streamlit guide](https://docs.streamlit.io/develop/concepts/ai-agents/coding-agents)
describes global installation, supported agents and Windows symlink
requirements. Do not commit the generated links to the repository.

## Update and verify

To update a manual installation, replace the installed folders with the
latest version and restart or reload the agent. Then check that:

1. each directory is named after its skill and contains `SKILL.md`;
2. the agent lists the skills, if it offers a listing; and
3. "parse these service logs and keep line evidence" activates
   `parsefabric`, and "write a custom parser for our audit format" activates
   `parsefabric-extend`.
