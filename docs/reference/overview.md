# Reference

Reference pages define stable contracts. They are not tutorials. Use them when
you already know what you want to do and need the exact command, schema,
artifact rule, or validation behavior.

## Reference Index

| Page | Use it for |
| --- | --- |
| [CLI Reference](cli.md) | Canonical `gridalyn` commands and command groups. |
| [YAML Reference](../workflows/workflow-yaml-reference.md) | Project and workflow YAML conventions. |
| [Report Schemas](reports.md) | Canonical JSON report structure and metadata. |
| [Semantic Model And Graph](semantic-graph.md) | Node/edge schema, ontology profile, and graph artifacts. |
| [FalkorDB Path](falkordb.md) | Migration path from Parquet graph artifacts to graph database backends. |
| [Artifact Policy](../development/artifact-policy.md) | What can be committed, generated, ignored, or published. |
| [Testing And Validation](../development/testing-and-validation.md) | Project verification ladder and repository checks. |

## Contract Style

Reference pages should answer:

- what the contract is called;
- which file, command, or API owns it;
- which inputs are required;
- which outputs are produced;
- how to validate it;
- what should remain stable for users.

Explanatory background belongs in [Platform](../platform/overview.md) or
[Core Concepts](../concepts/overview.md). Step-by-step instructions belong in
[Start](../getting-started/quickstart.md) or [Demos](../projects/overview.md).
