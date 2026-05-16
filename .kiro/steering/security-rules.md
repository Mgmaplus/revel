---
inclusion: always
---

# Security-First Development

## Always implement (MUST)

1. Input validation at all boundaries
2. Output encoding for the target context
3. Authentication for identity where required
4. Authorization for permissions before actions
5. Secure defaults and configuration hardening
6. Least privilege for credentials, tokens, and roles
7. Defense in depth across layers
8. Fail securely without leaking secrets

## Security research required

* Consult Context7 MCP for stack-specific security guidance
* Review OWASP guidance for the application type
* Check recent security advisories for dependencies
* Enable security-focused linting and scanners in CI

## Secrets and data handling (MUST)

* **Do not log secrets or sensitive data** (API keys, tokens, passwords, PII)
* Use a vault, secret manager, or parameter store. **Never commit secrets**
* Redact sensitive fields in logs, errors, and debug output
* Use environment variables or secure configuration for runtime secrets

## Security escalation (MUST REFUSE)

**Refuse and escalate** if asked to:
- Generate code that bypasses authentication or authorization
- Store secrets in code, configuration files, or version control
- Disable security features without documented business justification
- Implement cryptography from scratch (use OpenSSL, libsodium, platform crypto APIs)
- Expose internal errors or stack traces to end users
- Process untrusted data without validation

## Security checklist for all changes

- Does this touch auth, validation, secrets, or crypto?
- Does this change behavior unexpectedly?
- Could this affect data integrity or external systems?
- Are all inputs validated at boundaries?
- Are outputs properly encoded for their context?
- Are errors actionable without leaking sensitive data?
