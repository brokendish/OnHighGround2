# Security policy

## Supported release status

This repository is preparing its first public release. A supported-release
maintenance policy has not yet been established.

## Reporting a vulnerability

Use GitHub Private Vulnerability Reporting for security-sensitive reports. Do
not include credentials, API keys, `.env` files, operator secrets, or other
sensitive material in a public issue. No personal email address is published as
a security contact.

If Private Vulnerability Reporting is unavailable, contact the repository owner
privately and do not disclose the details in a public issue.

## Deployment boundary

The public application intentionally does not provide `/admin` management
routes. Privileged operator services are a separate optional workflow; see
[docs/operator-setup.md](docs/operator-setup.md). Keep public and operator
configuration files separate and never commit their secrets.
