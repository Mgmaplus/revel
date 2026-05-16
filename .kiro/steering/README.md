---
inclusion: manual
---

# Kiro Steering Rules

> **Note:** This index lists agents and components from the full multi-agent workspace. Your local checkout may only contain one of them — entries are for orientation, not assumed local paths.

This directory contains modular steering rules that guide Kiro's behavior when assisting with code development in this multi-agent system.

## File Organization

### Always Included (Core Rules)
These files are automatically included in every Kiro interaction:

- **`security-rules.md`** - Security-first development practices, secrets handling, validation requirements
- **`workflow-and-quality.md`** - Task sizing, quality gates, implementation workflow, research guidelines
- **`code-style.md`** - Code style, naming conventions, error handling, performance guidelines
- **`escalation.md`** - When and how to escalate blocking issues
- **`project-overview.md`** - System architecture, agent list, module structure

## How It Works

### Inclusion Modes

1. **`inclusion: always`** - Loaded in every interaction
2. **`inclusion: fileMatch`** - Loaded when file patterns match
3. **`inclusion: manual`** - Loaded only when explicitly referenced

### File Match Patterns

Files use glob patterns in frontmatter:
```yaml
---
inclusion: fileMatch
fileMatchPattern: '**/*.py'
---
```

## Benefits of This Structure

1. **Reduced token usage** - Only relevant rules are loaded
2. **Better organization** - Clear separation of concerns
3. **Easier maintenance** - Update specific sections independently
4. **Contextual loading** - Rules appear when needed

## Updating Rules

When updating rules:
1. Keep files focused on a single concern
2. Use appropriate inclusion mode
3. Test that file match patterns work correctly
4. Update this README if adding new files

