# Security Policy

## Supported Version

Security fixes target the current `main` branch and the production release
listed in `CHANGELOG.md`.

## Reporting

Do not open a public issue for credentials, unauthorized message delivery,
remote execution, exposed Airflow access, or production data disclosure. Use
GitHub private vulnerability reporting for this repository.

Include the affected component, reproduction steps, impact, and any evidence
that can be shared without exposing production secrets.

## Scope

Production Variables, Connections, passwords, API keys, email addresses, device
credentials, database backups, and Fernet/JWT keys must not be committed or
printed by operational tooling. Real notification tests require explicit human
approval.
