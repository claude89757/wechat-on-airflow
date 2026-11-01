# Scoped Verification

The required exact-commit `CI / verify` remains the release gate. Normal pushes
and pull requests select components from the diff. Documentation and frontend-only
changes do not start PostgreSQL or install and test the Python application.
Python sources, tests, backend, Sender, control-plane and unknown changes retain
the complete Python suite, including database contracts. MCP authentication tests
remain mandatory when the corresponding MCP component changes.

Scheduled CI runs all component checks daily at 20:17 UTC. Manual CI dispatch also
runs all checks. These runs never deploy or send notifications. Failures appear
in Actions and must be triaged; this does not create a separate alert transport.

During local iteration run focused checks for the affected component. Use full
`make verify` for shared code, dependency, release-control or ambiguous changes.
Documentation-only work needs diff/link checks; frontend-only work needs
`make webapp-check`; MCP-only work needs its package tests and security checks.
Never substitute a locally successful check for the exact pushed commit gate.

Use the existing unified release entry and component planner. Protected identities,
exact commits, deployment health and separate high-risk approvals are unchanged.
Natural observation remains asynchronous. This optimization does not yet publish
CI-built images for deployment reuse or remove release tagging requirements.
