---
name: semantic-db-implement
description: Execute implementation plans by writing code, modifying files, and creating resources. Triggers on "implement", "code this up", "build this", "start coding" — whenever user wants to turn a plan into working code. Consumes plans from specs/ directory or inline, applies code changes directly to the codebase. Tech-agnostic — works with any language/framework. Asks light clarifying questions only for critical unknowns (file paths, dependencies). Outputs code changes to project files; does not commit.
compatibility: Reads from specs/ directory, edits project files, matches existing code style
---

## When to Use This Skill

Use when user explicitly says: "implement X", "code this up", "build X", "start coding X", or "let's build X". After a plan is ready (from semantic-db-planning skill or external plan), use this skill to execute it.

This skill is NOT for code review, testing, or planning—it's for transforming architectural plans into working code.

## Workflow

### Phase 0: Locate & Parse Plan

Find the plan to implement:
1. Check `specs/` directory for markdown file matching task name
2. If no file found, ask user to provide plan (inline or file path)
3. Parse plan structure: extract implementation steps, file changes, code examples, architecture

If plan is ambiguous or incomplete, ask user to clarify BEFORE starting coding.

### Phase 1: Light Questions (Critical Unknowns Only)

Ask ONLY if the plan leaves critical gaps:

- **File paths**: "Plan says 'add auth middleware' but doesn't specify file location. Assume `src/middleware/auth.ts`?"
- **Dependencies**: "Plan mentions 'bcrypt' but doesn't specify if already installed. Should I add to package.json?"
- **Naming conflicts**: "I see existing `UserController.js` and plan wants to add user auth. Should I extend existing or create `UserAuthController.js`?"
- **Tech specifics**: "Plan mentions 'ORM' but project uses raw SQL. Should I keep SQL or add ORM layer?"

Do NOT ask for things the plan already specifies. Do NOT ask for subjective preferences (styling, naming conventions). Those are covered in Phase 2.

### Phase 2: Prepare Environment

Before coding:
1. **Explore existing code**: Read relevant files to understand current structure, patterns, imports
2. **Match style**: Examine existing code for:
   - Language/framework patterns
   - Naming conventions (camelCase, snake_case, etc.)
   - Import/require patterns
   - Test file structure (if tests exist)
3. **List dependencies**: Note what new packages (if any) the plan requires; check if already installed
4. **File map**: Create mental map of files to create vs modify

### Phase 3: Execute Implementation Steps

Follow the plan's numbered steps exactly. For each step:

1. **Read the step** — understand what code/resource to create
2. **Implement** — write code, create files, modify existing files
3. **Match style** — ensure code follows project conventions (use existing code as template)
4. **Use plan examples** — if plan provides code examples, adapt them; don't rewrite from scratch
5. **Move to next step** — no pause; execute all steps in sequence

**Key principles:**
- **Be literal**: If plan says "add route `/api/users/:id`", create that endpoint, not `/api/v1/users/:id`
- **Complete steps**: Each step should be independently functional if possible; don't create stubs
- **Preserve existing**: Don't refactor unrelated code; only change what the plan asks for
- **New files**: If plan requires new files (e.g., `src/auth/oauth.py`), create them with full content, not skeleton
- **Dependencies**: Add to package.json / requirements.txt / pyproject.toml if needed; don't assume they're installed

### Phase 4: Handle Unknowns

If you encounter something the plan doesn't specify clearly:

1. **Check existing code**: Does the codebase have a similar pattern? Use it
2. **Make assumptions explicit**: Add a comment noting your choice: `// Assuming JWT tokens stored in cookies per plan section 3.1`
3. **If still unclear**: STOP and ask user for clarification. Do NOT guess on critical decisions.

**Don't guess on:**
- Database schema (ask what columns to add)
- API response format (ask what shape the response should have)
- Authentication method (ask which auth pattern to use)
- Data encryption strategy (ask how sensitive data should be protected)

**OK to assume:**
- File location if pattern is clear
- Naming conventions (match existing code)
- Error handling pattern (match existing code)
- Logging format (match existing code)

### Phase 5: Output & Summary

After all steps complete:

1. **List changes**: Show files created / modified
2. **Brief summary**: 2-3 sentences on what was implemented
3. **Next steps**: Note if tests should be run, if deployment needed, etc.
4. **Do NOT commit**: Skill outputs code changes only; user decides when to commit

## Example: What Good Looks Like

**Good implementation:**
- Follows every step in the plan
- Code matches existing project style
- New files created with full, working content
- Only files specified in plan are touched
- Comments added for non-obvious choices
- If plan has code examples, they're adapted to the codebase

**Weak implementation:**
- Skips steps or changes plan without asking
- Code style inconsistent with project
- Creates stub files that aren't functional
- Modifies unrelated files
- Ignores plan's architecture (adds bad patterns)
- Doesn't ask for clarification when needed

## Integration with semantic-db-planning Skill

This skill works standalone—it doesn't require the planning skill to have run first. However:

- If a plan was generated by semantic-db-planning, it will be in `specs/<task-name>.md`
- This skill will find and consume it automatically
- If no plan exists, user provides one (inline or path)

The skills are independent; either can be used separately or together.

## Tech-Stack Agnostic

This skill works with any language/framework:
- **Backend**: Node.js, Python, Go, Ruby, Java, etc.
- **Frontend**: React, Vue, Angular, Svelte, etc.
- **Database**: PostgreSQL, MongoDB, MySQL, DynamoDB, etc.
- **Infrastructure**: Docker, Kubernetes, Terraform, etc.

The approach is the same: read the plan, explore the codebase for patterns, then apply changes following project conventions.
