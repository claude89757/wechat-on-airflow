# Dependency maintenance policy

This repository follows a stability-first dependency policy.

## Default behavior

Routine Dependabot version-update pull requests are disabled for Python, the web app, GitHub Actions, and Docker images. Dependabot remains configured with `open-pull-requests-limit: 0` so that repository security updates can still be raised when Dependabot security updates are enabled in the repository settings.

Dependency versions are not advanced merely because a newer release exists. A non-security upgrade must be opened deliberately for a concrete production need, compatibility requirement, or scheduled maintenance window.

## Security updates

Security updates are reviewed as isolated changes. They are not automatically rebased, rewritten, approved, or merged by repository workflows. Each security change must pass exact-head CI and receive a compatibility review before merge. Production deployment remains a separate explicit operation.

## Maintenance windows

A broader dependency refresh is performed only when one of these conditions applies:

- a security advisory affects an exercised code path;
- a provider or platform ends support for the pinned version;
- a product change requires a newer dependency;
- an explicitly approved maintenance window is opened.

The objective is a small, explainable dependency delta rather than continuous upgrade churn.
