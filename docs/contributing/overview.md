# Contributing

This section is for anyone changing the repository: the SDK under
`gridalyn/`, a study under `projects/`, the tests, or these pages. Each page
owns one topic.

| Page | Read it when |
| --- | --- |
| [Architecture Rules](module-boundaries.md) | You are deciding where new code goes, or a boundary test failed. |
| [Conventions](conventions.md) | You are naming a function or stage, formatting code, writing a package `__init__.py`, or raising an error. |
| [Development Workflow](developer-workflow.md) | You are setting up, deciding what to commit, or reading a CI result on your pull request. |
| [Testing And Validation](testing-and-validation.md) | You need to know which check proves your change, and how to read it. |
| [Operator Verification](verification.md) | You changed a generator, a simulation kernel or the runner, and need what CI cannot run. |
| [Releasing](releasing.md) | You are tagging a version or minting the DOI. |

## The short version

1. Set up with `pip install -e ".[dev]"` and `pre-commit install`
   ([Development Workflow](developer-workflow.md#set-up)).
2. Put reusable behaviour in `gridalyn/`, in the lowest layer that can own
   it; keep study scripts thin ([Architecture Rules](module-boundaries.md)).
3. Run the narrowest check that covers the change, then widen
   ([Testing And Validation](testing-and-validation.md#when-to-run-which-check)).
4. Know which CI gate will judge the change and run it locally first
   ([What CI checks on your pull request](developer-workflow.md#what-ci-checks-on-your-pull-request)).
5. If a study's pinned result moves, that is a deliberate re-base with a
   recorded reason, never a silent baseline update
   ([Recording a re-base](verification.md#recording-a-re-base)).

`CONTRIBUTING.md` at the repository root is the same entry point for readers
on GitHub.
