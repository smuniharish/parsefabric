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

## Update and verify

To update a manual installation, replace the installed folders with the
latest version and restart or reload the agent. Then check that:

1. each directory is named after its skill and contains `SKILL.md`;
2. the agent lists the skills, if it offers a listing; and
3. "parse these service logs and keep line evidence" activates
   `parsefabric`, and "write a custom parser for our audit format" activates
   `parsefabric-extend`.
