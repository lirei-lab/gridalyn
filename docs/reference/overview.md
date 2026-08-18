# Reference

Reference pages define stable contracts. They are not tutorials. Use them when
you already know what you want to do and need the exact command, schema,
artifact rule, or validation behavior.

## Reference Index

| Page | Use it for |
| --- | --- |
| [CLI Reference](cli.md) | Canonical `gridalyn` commands and command groups. |
| [Python API Reference](python-api.md) | Auto-generated docstring reference for the seven layer facades. |
| [Public API Index](public-api.md) | Curated index of every supported import, by layer. |
| [Workflow YAML](workflow-yaml.md) | `workflow.yaml` stage and dependency conventions. `project.yaml`'s own contract is documented narratively in [Projects](../components/projects.md) and [Project Template](../guides/project-template.md), since its fields vary by study. |
| [Report Schemas](report-schema.md) | Canonical JSON report structure and metadata. |
| [Semantic Model And Graph](semantic-graph.md) | Node/edge schema, ontology profile, query API, and graph artifacts. |
| [FalkorDB Path](falkordb.md) | What exists today (a Cypher-export helper) versus what a live FalkorDB connection would require (not implemented). |
| [Artifact Policy](artifact-policy.md) | What can be committed, generated, ignored, or published. |
| [Glossary](glossary.md) | One-line definitions of the terms the rest of the site uses without redefining. |
| [Testing And Validation](../contributing/testing-and-validation.md) | Project verification ladder and repository checks. |

## Contract Style

Reference pages should answer:

- what the contract is called;
- which file, command, or API owns it;
- which inputs are required;
- which outputs are produced;
- how to validate it;
- what should remain stable for users.

Explanatory background belongs in [Components](../components/overview.md).
Step-by-step instructions belong in [Start](../start/quickstart.md) or
[Guides](../guides/overview.md).
