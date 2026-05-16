---
inclusion: always
---

# Escalation: Definition and Process

"Escalate" means **stop work and communicate a blocking issue to the user** using a clear, structured format.

## When to escalate (MUST)

- Security boundaries or trust models are unclear
- Required credentials, secrets, or access are missing
- Data deletion, migration, or schema changes are requested
- External API contracts or breaking changes are ambiguous
- Production configuration or infrastructure changes need approval
- Conflicting requirements cannot be resolved by precedence rules
- Multiple approaches exist with significant trade-offs
- Requested action violates security rules

## How to escalate

Use this structured format:

```
**ESCALATION REQUIRED**

**Issue**: [One-sentence summary]

**Context**: [Brief explanation of what you were trying to do]

**Blocker**: [Specific reason you cannot proceed]

**Options**: [If applicable, 2-3 alternatives with trade-offs]

**Required to unblock**:
- [ ] [Specific item 1]
- [ ] [Specific item 2]

**Impact if not resolved**: [What happens if this isn't addressed]
```

## Example escalation

```
**ESCALATION REQUIRED**

**Issue**: Cannot determine authentication strategy for new API endpoint

**Context**: Adding `/api/users/{id}/delete` endpoint. Existing endpoints use mix of JWT (newer) and session cookies (older).

**Blocker**: No documented authentication standard. Security-first principle requires auth, but don't know which to implement.

**Options**:
1. Use JWT (matches newer endpoints, stateless) - May break old clients
2. Use session cookies (matches older endpoints) - Inconsistent with modern endpoints  
3. Support both (most compatible) - More complex, larger attack surface

**Required to unblock**:
- [ ] Confirmation of which auth method to use, or
- [ ] Approval to support both with preference order

**Impact if not resolved**: Cannot implement endpoint securely
```

## Escalation anti-patterns (avoid)

- ❌ "I'm not sure what to do here" (vague, no options)
- ❌ "Should I use A or B?" (no context or trade-offs)
- ❌ "This is really hard" (not actionable)
- ❌ Guessing and implementing anyway

## Proactive Problem Solving

Before implementation, ask:

1. What assumptions am I making and how do I validate them?
2. What could break and how will we mitigate it?
3. How will this scale and degrade gracefully?
4. What happens if it fails and how do we recover?
5. How will we know it's working in production?
6. What will maintenance and upgrades look like?

## When NOT to be proactive

- Don't add infrastructure not requested (monitoring, CI/CD) for simple scripts
- Don't optimize or refactor working code unless requested, broken, or blocking
- Don't add tests to legacy code unless fixing that area
- Don't change architecture without discussing trade-offs
