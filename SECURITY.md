# Security Policy

## Reporting a vulnerability

If you find a security issue in this repository (for example, a leaked credential, an unsafe default in the deploy scripts, or a vulnerable dependency), please report it privately rather than opening a public issue.

- Preferred: use GitHub's private vulnerability reporting on this repository (the "Report a vulnerability" button under the Security tab).
- Alternative: open a minimal issue that says only that you have found a security concern and asks for a private channel, without disclosing details publicly.

Please include enough detail to reproduce the issue and, if possible, a suggested fix. You can expect an acknowledgement within a few days.

## Scope and good practices

A few things to keep in mind when running this project:

- Secrets (such as `NOTION_TOKEN`) belong in Google Cloud Secret Manager or a local, git-ignored `.env`, never in committed files. Only `.env.example` with placeholder values is tracked.
- The deploy scripts deploy specialist services with `--allow-unauthenticated` for convenience. Do not use that setting beyond local development or a throwaway project; require authentication and restrict access with IAM.
- Use Application Default Credentials (`gcloud auth application-default login`) rather than long-lived service-account keys.
- Generated image URLs are short-lived signed URLs (one hour by default).

## Supported versions

This repository tracks a single main branch. Fixes are applied to `main`; there are no long-term support branches.
