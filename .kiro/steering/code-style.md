---
inclusion: always
---

# Code Style and Readability

## Core Principles

* **Clarity over brevity.** Avoid cleverness that reduces understanding
* **Consistent naming.** Follow language norms
* **Consistent formatting.** Use automated formatters
* **Comments explain the why** and nonobvious decisions
* **Keep functions and modules small** with single responsibility
* **DRY.** Factor shared logic into reusable units
* **Encapsulate complexity** behind clear interfaces

## Style precedence

1. **Match local style when contributing to existing files**
2. For greenfield projects, follow language conventions
3. If repo style conflicts with security or correctness, propose fixing the style

## Refactoring discipline

* **Note opportunities for refactoring** as technical debt without implementing them unless:
  - Explicitly requested by the user
  - Blocking current work
  - Part of fixing a bug in that code area
  - Trivial and side-effect-free

* **When noting technical debt**, use specific markers:
  - `TODO(refactor): [description]` in code comments
  - Document in `TECHNICAL_DEBT.md` if the project has one
  - Include in PR description under "Future Improvements"

## Default Naming Conventions

### Python
- Functions/variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_CASE`
- Modules: `snake_case.py`
- Type hints encouraged

### JavaScript / TypeScript
- Functions/variables: `camelCase`
- Classes/React components: `PascalCase`
- Files: `camelCase.ts` or `PascalCase.tsx` for components
- Strict mode or strict `tsconfig.json`

### Go
- Functions/variables: `camelCase` (unexported), `PascalCase` (exported)
- Files: `snake_case.go`
- Packages: Short, single-word, lowercase

### Rust
- Functions/variables: `snake_case`
- Types/traits: `PascalCase`
- Constants: `UPPER_CASE`
- Modules/files: `snake_case`

### Java / C#
- Methods/variables: `camelCase`
- Classes/interfaces: `PascalCase`
- Constants: `UPPER_CASE` (Java) or `PascalCase` (C#)

## Error Handling and Observability

* **Fail fast and fail loud** with actionable messages that do not expose secrets
* Prefer typed or structured errors
* Use structured logs with levels (DEBUG, INFO, WARN, ERROR) and stable fields
* Include correlation or trace IDs where available
* Add metrics and basic health checks for new components
* **MUST** ensure error handling covers:
  - Network timeouts and connection failures
  - Partial failures and degraded states
  - Retries with exponential backoff and jitter
  - Circuit breakers for external dependencies
  - Graceful degradation when dependencies fail

## Performance and Resource Management

* Choose appropriate data structures and algorithms for expected scale
* **Avoid premature optimization.** Optimize only after profiling
* **MUST** manage resources correctly:
  - Use RAII, `with`, `defer`, `finally`, or `try-with-resources` for cleanup
  - Close files, sockets, database connections, and handles explicitly
  - Free or release memory, locks, and semaphores
* **Use thread-safe data structures or explicit synchronization.** Document thread-safety assumptions
* Consider concurrency, contention, and race conditions
