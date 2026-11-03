# Development workflow

- main contains reviewed stable source, not an automatically deployed production release.
- Use feature/topic or fix/topic branches; open pull requests to main.
- Local .githooks/pre-push prevents direct main pushes on configured clones; it is NOT GitHub server-side branch protection. Configure GitHub branch rules separately.
- Include scope, tests, security assessment and rollback in each pull request.
- Keep English UI labels, light theme and LTR layout unless requirements change.
- Run CI static checks; do not invoke live power/TV commands in CI.
- Document new configuration in config/devices.example.json, never private devices.json.
- Never check in pairing material, SSH keys, data/history, logs or backups.
- Read-only agent uses signed outbound HTTPS (no inbound SSH server). Future command APIs must be allowlisted and least-privileged; no arbitrary shell execution.
- Back up running Pi installation and explicitly validate differences before deploying new code.
- Use commit messages describing one logical change.
