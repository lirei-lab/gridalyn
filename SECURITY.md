# Security Policy

## Scope

Gridalyn is a research SDK. It runs locally, reads YAML configuration and data
files, and writes artifacts to disk. It ships no server, no database and no
authentication, and it is not intended to be exposed to untrusted input or run
as a network service.

Within that scope, the things worth reporting are:

- Code execution reachable from a `project.yaml` or `workflow.yaml` that a user
  might obtain from a third party. Workflow stages run as shell subprocesses, so
  a malicious workflow file is equivalent to a malicious script — but a path by
  which *data* files lead to execution would be a genuine issue.
- Path traversal that lets a project write outside its own workspace.
- Deserialization of untrusted files (pickle, HDF5) reached without an explicit
  user action.

The bundled dashboard is a static single-page application built with Vite and
served by nginx. It reads artifact files and performs no authentication; it is
meant for local or trusted-network use.

## Reporting

Report suspected vulnerabilities privately to **lirei.info@uqtr.ca** rather
than opening a public issue. Please include what you did, what happened, and the
version or commit you were on.

Expect an acknowledgement within a few working days. This is an academic project
without a dedicated security team, so response times depend on availability.

## Supported versions

The project is pre-1.0 and only the `main` branch receives fixes. There are no
backports to earlier tags.
