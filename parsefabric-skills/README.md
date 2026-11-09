# ParseFabric Agent Skills

This directory distributes two Agent Skills that teach coding agents to use
the `parsefabric` package correctly. They are not part of the Python package
and add no runtime behavior.

| Skill | Use it to |
| --- | --- |
| [`parsefabric`](skills/parsefabric/SKILL.md) | Use ParseFabric in an application: parse logs, JSON, tracebacks, command output and mixed documents with evidence, store and rebuild aggregates, stream and partition work, send telemetry, write checked model summaries, and troubleshoot |
| [`parsefabric-extend`](skills/parsefabric-extend/SKILL.md) | Extend ParseFabric: subclass one of its abstract base classes, such as a parser, codec, execution backend, sink or language model, and prove it with the contract checks |

Install both with the [skills CLI](https://github.com/vercel-labs/skills),
which finds them through [`skills.sh.json`](../skills.sh.json):

```bash
npx skills add smuniharish/parsefabric                          # both
npx skills add smuniharish/parsefabric --skill parsefabric      # one
```

Other ways to install are in the
[documentation](https://parsefabric.readthedocs.io/en/latest/agent-skills/install/).

## Layout

Each skill follows the [Agent Skills specification](https://agentskills.io/specification):

```text
skills/<skill>/
??? SKILL.md      # frontmatter, workflow, rules, gotchas, links to every file
??? references/   # focused documents, one level deep, read only when a task needs them
??? scripts/      # offline checks with --help, --json, and meaningful exit codes
??? assets/       # templates the agent copies into the project, each with its tests
??? evals/        # evals.json, trigger_queries.json, and the input files they use
```

| Skill | Scripts | Assets |
| --- | --- | --- |
| `parsefabric` | `verify_setup.py`: checks the installation and parses, stores and rebuilds a sample offline; LangChain too when installed (`--langchain` to require it) | `test_parsing.py` |
| `parsefabric-extend` | `check_extension.py`: detects which abstract base class an extension subclasses and runs its contract check | `parser_template.py`, `test_parser.py`, `sink_template.py`, `test_sink.py` |

Every Agent Skills host reads the same directories, so there is no separate
copy for Claude Code, Codex, Cursor or GitHub Copilot.

## Format

- `name` matches the directory. The `description` starts with "Use this skill
  when", names near misses, and hands over to the other skill where they
  meet.
- `license`, `compatibility` and `metadata.version` are set. The version
  equals the `parsefabric` release the skill describes.
- `SKILL.md` stays short and links every reference with the task that needs
  it. Scripts and assets are referenced by paths relative to the skill
  directory.

## Maintaining the skills

When the public API or documented behavior changes:

1. Update the affected skill, and `metadata.version` in both skills with each
   release.
2. Check every changed snippet and claim against the code, tests or
   documentation. Leave out anything that is not implemented.
3. Add or update an eval when the change affects what an agent should do.
4. Run the checks in [`validation/README.md`](validation/README.md).

The skills are covered by the repository's Apache License 2.0; see
[LICENSE](../LICENSE).
