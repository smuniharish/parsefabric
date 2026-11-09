# Evaluating the skills

The skills are checked in three ways: automated tests on every change,
evaluations against real tasks, and a review of every claim against its
source. The [validation guide](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/validation/README.md) has the full
procedure.

## Automated checks

```bash
uv run pytest tests/skill
uvx --from skills-ref agentskills validate parsefabric-skills/skills/parsefabric
uvx --from skills-ref agentskills validate parsefabric-skills/skills/parsefabric-extend
```

`tests/skill` validates both skills against the specification, checks that
every reference is linked and every link resolves, checks the evals, and runs
the bundled scripts and templates. Continuous integration also runs
`verify_setup.py --langchain` and `check_extension.py` against the built
wheel, and the documentation tests compile every Python snippet in the
skills.

## Evaluations

Each skill has an `evals/` folder in the format described in
[Evaluating skills](https://agentskills.io/skill-creation/evaluating-skills):

- `evals.json`: realistic tasks with input files, the expected result, and
  assertions a grader can verify.
- `trigger_queries.json`: requests that should load the skill and near misses
  that should not, split into training and validation sets. No request
  triggers both skills.

Run each task with and without the skill, grade every assertion with its
evidence, and change the skill wherever the agent did no better with it.
