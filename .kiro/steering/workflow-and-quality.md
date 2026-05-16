---
inclusion: always
---

# Workflow and Quality Gates

## Rule Precedence

When rules conflict, apply this hierarchy:

1. **Security requirements** override all other concerns
2. **User-provided explicit instructions** override defaults
3. **Repo-specific conventions** override language defaults  
4. **Documented team standards** override assistant defaults
5. When rules conflict without clear precedence, escalate rather than guess

## Rule Priority Levels

- **MUST**: Non-negotiable requirements (security, correctness, safety)
- **SHOULD**: Strong defaults that apply unless there's good reason otherwise
- **MAY**: Context-dependent suggestions that improve quality

## Fixing vs Suppressing Issues (MUST)

When asked to fix linter errors, type errors, or test failures:

**NEVER suppress issues by:**
- Adding `eslint-disable` comments
- Adding rules to `.eslintrc` to ignore warnings/errors
- Adding `@ts-ignore` or `@ts-expect-error` comments
- Modifying `tsconfig.json` to weaken type checking
- Skipping or disabling failing tests

**ALWAYS fix the root cause:**
- Refactor code to satisfy linter rules
- Fix type errors by correcting types or logic
- Update tests to match new behavior or fix bugs
- If a rule is genuinely inappropriate, discuss with the user first

**Exception:** Only suppress when explicitly requested by the user or when the rule is demonstrably incorrect for the specific case (document why in a comment).

## Workflow Scaling by Task Size

### **Trivial (<10 lines, simple fixes)**
**Mental security checklist first:**
- Does this touch auth, validation, secrets, or crypto? → Treat as Small
- Does this change behavior unexpectedly? → Treat as Small
- Could this affect data integrity or external systems? → Treat as Small

If no concerns: implement directly, run formatter and basic tests

**Examples:** Typo fix, dead code removal, log message update

### **Small (10-100 lines, single feature)**
- Brief written plan with key decision points
- Implement with local style matching
- Unit tests for new logic
- Format, lint, verify

**Examples:** New utility function, bug fix with test, config parameter

### **Medium (100-500 lines, feature or refactor)**
- Written plan with sequenced subtasks
- Staged implementation with checkpoints
- Full test coverage of new paths
- Documentation updates
- Full quality gate review

**Examples:** New API endpoint, module refactor, external service integration

### **Large (>500 lines, architecture changes)**
- Full workflow with written design doc
- Incremental PRs or feature flags
- Integration and performance testing
- Monitoring and rollback planning
- Team review before merge

**Examples:** Database migration, new service, framework upgrade

---

## Implementation Steps

### Step 1: Research and requirement analysis
* Query Context7 MCP and sources of truth
* Clarify functional requirements: inputs, outputs, edge cases, constraints
* Clarify nonfunctional requirements: performance, security, scalability, reliability, operability
* Identify dependencies, external integrations, and data flows

### Step 2: Strategic planning and architecture
* Break down work into small, sequenced tasks. **Implement prerequisites first**
* Plan file structure, interfaces, and data flow
* **Security-first design:**
  - Trust boundaries and validation points
  - Authentication and authorization needs
  - Data handling, storage, and retention
  - Threat model and attack surface
* **Plan observability:** logs, metrics, traces, and alerts
* **Note rollback strategy** and potential blast radius

### Step 3: Implementation
* Favor clear, small, single-responsibility units
* Separate pure logic from side effects. Use dependency injection for IO and services
* Follow repo style rules, language idioms, and naming conventions
* **MUST** implement:
  - Input validation at all boundaries
  - Output encoding for the target context
  - Comprehensive error handling with actionable messages
  - Secure defaults
* **Close files, connections, and handles explicitly** using context managers, RAII, defer, or finally

### Step 4: Validation and testing
* Unit test pure logic with fast feedback
* Integration test critical paths and external boundaries
* Cover edge cases and failure modes identified in planning
* Validate performance on realistic data where relevant
* Cross-check against documentation for API correctness and deprecations

### Step 5: Documentation and future proofing
* Document public APIs, complex logic, security assumptions, and usage examples
* Note technical debt, temporary workarounds, and upgrade paths for dependencies
* Capture monitoring expectations and runbooks when adding or changing behavior

---

## Quality Gates

Quality gates are **tiered by change size** to balance rigor with efficiency.

### Required for ALL changes (MUST)

- [ ] Formatter applied and linter passes
- [ ] TypeScript type checks pass (use `getDiagnostics` or `pnpm checkTypesAll`)
- [ ] No security regressions or new vulnerabilities  
- [ ] Code compiles/runs without errors
- [ ] Existing tests pass
- [ ] No hallucinated APIs

### Required for NEW features (SHOULD)

- [ ] Context7 MCP and primary docs consulted
- [ ] Task runner used for build, test, lint, format
- [ ] Unit and integration tests added/updated
- [ ] Security best practices implemented
- [ ] Errors are actionable and don't leak data
- [ ] Documentation updated
- [ ] Commit follows Conventional Commits
- [ ] PR description complete

### Required for LARGE changes (MUST)

- [ ] Performance validated or profiled
- [ ] Observability added/updated
- [ ] Rollback plan verified
- [ ] Open questions recorded as TODOs
- [ ] Stakeholder review completed
- [ ] Breaking changes documented with migration guide

### Quick reference by task size

| Task | Format/Lint | Tests | Docs | PR | Observability | Review |
|------|-------------|-------|------|----|---------------|--------|
| Trivial | ✓ | △ | ✗ | ✗ | ✗ | ✗ |
| Small | ✓ | ✓ | △ | △ | ✗ | ✗ |
| Medium | ✓ | ✓ | ✓ | ✓ | △ | △ |
| Large | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

✓ = Required, △ = If applicable, ✗ = Not required

## Sources of Truth and Research

### Documentation lookup priority

1. Context7 MCP for library-specific documentation
2. Official vendor docs and API references
3. Standards and foundations (OWASP, RFCs, language specs)
4. Maintained framework guides and security advisories
5. Reputable community sources with recent activity

### Research rules

* **Limit documentation searches to 3-5 queries per subtask.** If gaps remain, proceed with best practice defaults and mark open questions as TODO
* **MUST** verify syntax, method signatures, deprecations, and current patterns before coding
* Record key links in the PR, commit message, or work log
* **Escalate immediately** rather than guessing when unclear

## Communication Style

- **Be concise.** Front-load key information
- **Show progress** on long operations
- **Explain "why"** for non-obvious decisions
- **When blocked, escalate using structured format**
- Format code in responses for readability unless implementing directly
