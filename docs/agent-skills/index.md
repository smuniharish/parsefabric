# Agent Skills

ParseFabric publishes two [Agent Skills](https://agentskills.io/specification)
that teach AI coding agents to use the library correctly. They are
documentation for agents: they add no runtime behavior and do not change how
ParseFabric is installed.

| Skill | Use it to |
| --- | --- |
| [`parsefabric`](parsefabric.md) | Use ParseFabric in an application: parse logs, JSON, tracebacks, command output and mixed documents with evidence, store and rebuild aggregates, stream and partition work, send telemetry, write checked model summaries, and troubleshoot. |
| [`parsefabric-extend`](parsefabric-extend.md) | Extend ParseFabric: subclass one of its abstract base classes, such as a parser, codec, execution backend, sink or language model, and prove it with the contract checks. |

Each skill's description names the tasks it covers and hands over to the
other skill where they meet, so an agent loads only the one it needs.

| Page | Contents |
| --- | --- |
| [Install](install.md) | The skills CLI and manual installation for Claude Code, Codex, Cursor and GitHub Copilot. |
| [Evaluation](evaluation.md) | The automated checks, evaluations and source review that keep the skills correct. |

The skills live in
[`parsefabric-skills/`](https://github.com/smuniharish/parsefabric/tree/main/parsefabric-skills) and follow the
library's releases: `metadata.version` in each `SKILL.md` equals the
`parsefabric` version it describes.
