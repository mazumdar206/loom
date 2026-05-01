# 1. Record Architecture Decisions

Date: {{ date }}

## Status

Accepted

## Context

We need to record the architectural decisions made on this project so that future
contributors understand why choices were made and can build on them rather than
re-litigating settled questions.

## Decision

We will use Architecture Decision Records, as described by Michael Nygard in
[Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

Each ADR lives in `docs/specs/adrs/` as a numbered Markdown file. The Architect
creates ADRs via the `create_adr` MCP tool. ADR numbers are sequential and gaps
indicate removed decisions.

## Consequences

- Anyone reading this project can find decisions and their rationale.
- New decisions extend the log; old ones are not modified (they may be superseded).
- The Architect is responsible for keeping ADRs current.
