# Contributing to ATAP

Thank you for contributing to ATAP.

ATAP is an open-source GIS-native research and engineering project founded and
stewarded by Enygma.

## Before You Start

1. Search existing Issues and Pull Requests.
2. For bugs, provide reproducible steps.
3. For substantial algorithmic or architectural changes, open an Issue or
   design discussion first.
4. State whether the change affects geometry, hierarchy, CRS behavior, vertical
   semantics, numerical output, schema, or default parameters.
5. Verify license compatibility for new dependencies.
6. Do not introduce code of uncertain provenance.

## Pull Requests

A Pull Request should:

- explain the problem and proposed solution;
- identify affected modules;
- link related Issues;
- describe user-visible or scientific behavior changes;
- include tests where reasonably possible;
- include before/after results for material algorithm changes;
- update documentation;
- disclose new third-party dependencies;
- disclose AI-generated code where materially relevant;
- avoid unrelated refactoring.

## Attribution

Human contributors should use their own attributable GitHub accounts wherever
practical.

Individual authorship is preserved through Git history, Pull Requests, reviews,
release records, and publication metadata where appropriate.

## Contributor License Agreement

External contributions may require explicit acceptance of the ATAP Contributor
License Agreement in [`CLA.md`](./CLA.md) through an auditable acceptance
mechanism designated by the project.

The CLA is intended to preserve long-term stewardship and lawful alternative
licensing where PT Enygma Solusi Negeri has sufficient rights.

## License

Covered ATAP Community Edition source is licensed under `AGPL-3.0-only`.

## Scientific Changes

Experimental methods should not silently replace the stable baseline.

Where practical, compare:

```text
stable baseline
vs.
experimental method
```

using the same reference data and validation criteria.

## AI-Assisted Contributions

AI-assisted development is permitted, but contributors remain responsible for:

- correctness;
- provenance;
- licensing;
- security;
- tests;
- documentation;
- validation;
- final acceptance.
