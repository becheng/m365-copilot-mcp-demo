# Replication Insights declarative agent

This directory is a Microsoft 365 declarative agent managed by the official
`wiqd@wiqd` plugin from `microsoft/wiqd`. Use its `wiqd` orchestrator skill and
`wiqd-core` workflow before changing manifests, instructions, actions, or lifecycle
configuration. If the host cannot expose the installed skill, read the official
installed SKILL.md and routed references directly and disclose that limitation.

Preserve generated schema versions and resolve file references through manifests.
Use `wiqd agent validate` before packaging or provisioning. Environment `offline`
is only a synthetic packaging fixture: never provision or publish it.

All database operations and metrics are mock, read-only data. No databases,
database connections, hosting resources, or anonymous server fallback are allowed.
Never commit tokens, client secrets, or generated user environment files.
