# Agent Skills

ParseFabric publishes an [Agent Skill](https://agentskills.io/specification)
that teaches AI coding agents how to integrate, configure, extend, test and
debug the library: which parser to choose, how to keep evidence, how to store
and rebuild events, and which shortcuts to avoid. The skill is documentation
for agents; it does not change how ParseFabric is installed or behaves.

| Component | Location |
| --- | --- |
| ParseFabric library | [`src/parsefabric/`](https://github.com/smuniharish/parsefabric/tree/main/src/parsefabric) |
| Agent Skill | [`parsefabric-skills/skills/parsefabric/`](https://github.com/smuniharish/parsefabric/tree/main/parsefabric-skills/skills/parsefabric) |
| Skill instructions | [`SKILL.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/SKILL.md) |

The skill uses only the standard `name` and `description` frontmatter, so one
copy works with every compatible agent.

## Install with the skills CLI

The [skills CLI](https://www.skills.sh/docs/cli) installs a skill directly
from GitHub:

```bash
npx skills add https://github.com/smuniharish/parsefabric/tree/main/parsefabric-skills/skills/parsefabric
```

Follow the CLI's prompts to choose your agent, then check that it placed a
`parsefabric` folder in that agent's skills directory.

## Install manually

Copy the complete
[`parsefabric` skill directory](https://github.com/smuniharish/parsefabric/tree/main/parsefabric-skills/skills/parsefabric),
including `SKILL.md`, into the location your agent reads.

### Claude Code

| Scope | Destination |
| --- | --- |
| Current repository | `.claude/skills/parsefabric/` |
| All local projects | `~/.claude/skills/parsefabric/` |

Restart Claude Code after copying the directory. Claude selects the skill when
a task matches its description, or you can invoke it with `/parsefabric`. See
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

Restart Cursor after copying the directory. In Agent chat, type `/` and select
`parsefabric`, or let Cursor activate it from its description. See
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

Copy the complete `parsefabric` folder into the skills directory documented by
your agent. No adapter is needed.

## Update and verify

To update a manual installation, replace the installed `parsefabric` folder
with the latest version from the repository and restart or reload the agent.

After installing, check that:

1. the directory is named `parsefabric` and contains `SKILL.md`,
2. the agent lists `parsefabric` among its skills, if it offers a listing, and
3. a task such as "parse these service logs and keep line evidence" activates
   the skill, or that you can invoke it explicitly.

The [distribution README](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/README.md)
and the [validation process](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/validation/README.md)
describe how the skill is maintained.
