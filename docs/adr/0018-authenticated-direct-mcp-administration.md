# ADR 0018: Authenticated Direct MCP Administration

## Status

Accepted on 2026-11-07. Supersedes the per-command browser confirmation in the
owner-authorized MCP administration of 2026-10-31.

## Context

Every host command needed its own five-minute browser approval and could run for
only 120 seconds, one at a time. Agents could not diagnose or repair a host without
a person clicking through each step. The owner asked for full server access once
authentication completes.

## Decision

A human who completes Cloudflare OAuth and belongs to the host's Access group runs
commands directly as root through `ops_exec`.

- The JWT checks, Access groups and the human-identity requirement stay. Machine
  service tokens still cannot run or read commands.
- Commands may run for up to an hour and in parallel; long ones are read later with
  `ops_result`.
- The audit log records command text instead of a digest, because it is now the only
  record of what ran. A command does not run if it cannot be audited.
- Repository releases stay in protected GitHub workflows.

## Consequences

Nothing technical stops an authenticated client from making a destructive change.
Rules about deleting data, rotating secrets and real notifications are now followed
by agents rather than enforced by the server. A prompt injection that reaches an
agent holding this connection can run as root, so command output and web content
stay untrusted data. Removing someone requires revoking their Access sessions and
OAuth grants as well as their group membership; emergency `withdraw` disables the
host channel.
