# Security and privacy

## Network boundary
The Raspberry Pi Python server binds only to loopback (127.0.0.1:8765). Tailscale Serve provides private HTTPS inside the Tailnet. Avoid Tailscale Funnel, router port forwarding and public SSH ports. Review Tailnet grants/ACL permissions; simply belonging to the Tailnet must not imply permission for privileged commands.

## Web request handling
The MVP validates Host and Origin and uses an HttpOnly cookie with a session CSRF token for POST operations. CSRF prevents a class of cross-site requests; **it is not user authentication**. Add explicit authentication/authorization before enabling sensitive Ubuntu agent actions or access by multiple users.

## Private files
Never commit:
- config/devices.json (LAN IPs, MAC addresses and device details)
- config/.aiopylgtv.sqlite (LG pairing material)
- data/history.jsonl (command records)
- .env files, SSH keys, logs, virtual environments, local backups

The provided config/devices.example.json contains non-routable documentation addresses and placeholder MAC values. Keep device-local files restricted to the intended Unix user, typically permissions 0600.

## Commands and operations
- Implement only explicitly allowlisted commands and parameters.
- Use a minimal dedicated agent privilege set for Ubuntu; never execute arbitrary submitted shell strings.
- Distinguish Wake-on-LAN packet transmission from verified power-on.
- Require confirmation for shutdown, restart, updates and other disruptions.
- Check for active jobs before shutdown and allow cancellation of scheduled actions.
- Log command attempts and results, but never tokens, cookies or credentials.
- Define data retention and backup rules.

## Release checks
1. Scan the Git diff for secrets, addresses, credentials and changes to allowed commands.
2. Verify static checks and tests pass.
3. Review PR, then merge main.
4. Back up live config and pairing database; never overwrite it from the repository.
5. Deploy explicitly with rollback support; verify private HTTPS and API health.
6. Do not test disruptive actions without explicit user approval.
