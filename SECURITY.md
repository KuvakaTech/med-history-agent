# Security Policy

## Supported Versions

Only the latest release on `main` receives security fixes.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub Issues.**

Email **security@kuvaka.io** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

You will receive a response within 48 hours. We aim to patch critical vulnerabilities within 7 days and disclose them publicly after a fix is released.

## Clinical Safety

This software processes medical information. If you discover a flaw that could cause:
- Incorrect or dangerous clinical advice to surface
- Failure to detect a documented red-flag condition
- Data leakage of patient-identifiable information

treat it as a **critical security issue** and follow the private disclosure process above.

## Scope

| In scope | Out of scope |
|----------|-------------|
| API authentication and authorisation | Rate limiting bypass for non-clinical endpoints |
| Patient data exposure | Spam / abuse of public endpoints |
| Prompt injection leading to clinical misguidance | Social engineering |
| Dependency vulnerabilities (CVE) | Issues requiring physical access |

## Responsible Disclosure

We follow a 90-day responsible disclosure policy. Researchers who report valid vulnerabilities in good faith will be credited in the release notes unless they prefer to remain anonymous.
