---
name: semantic-db-review
description: Review code for correctness, quality, performance, security, and test coverage. Triggers on "review", "check this code", "code review", "/review" — whenever user wants feedback on uncommitted changes. Reviews staged files, modified files, or user-specified files. Reports all findings ranked by severity (critical first) with suggested fixes. Explores project patterns to match existing conventions. Does NOT auto-fix; user decides whether to apply suggestions.
compatibility: Reads git status, reviews uncommitted changes, explores project codebase
---

## When to Use This Skill

Use when user explicitly says: "review this", "code review", "check my code", "find issues", "review changes", or "/review". 

This skill reviews uncommitted code changes and provides feedback on:
- **Bugs & Correctness**: Logic errors, crashes, data corruption, edge cases
- **Code Quality**: Style violations, DRY violations, simplification opportunities, readability
- **Performance**: N+1 queries, inefficient algorithms, memory leaks, unnecessary allocations
- **Security**: SQL injection, XSS, auth bypass, credential leaks, unsafe patterns
- **Tests**: Missing test coverage, untested branches, test gaps for new functionality

## Workflow

### Phase 0: Scope & Discover

Determine what to review:

1. **Check git status**: Are there staged files? Modified files? Untracked files?
2. **Ask if needed**: "Should I review staged changes, all modified files, or specific files you mention?"
3. **Explore project**: Read existing code to understand patterns, conventions, architecture
4. **Set context**: Note language, framework, testing strategy, security requirements

### Phase 1: Review Uncommitted Changes

For each file in scope:

1. **Read the file**: Understand what changed and why
2. **Check against patterns**: Compare against existing project patterns and best practices
3. **Analyze for issues**: Look for bugs, quality problems, perf issues, security flaws, test gaps
4. **Categorize findings**: Critical, Warning, Suggestion, Nitpick

### Phase 2: Evaluate Findings

For each finding:

1. **Assess severity**:
   - **Critical**: Crashes, data loss, security breach, logic error that breaks feature
   - **Warning**: Code smell, performance problem, missing test, style violation affecting readability
   - **Suggestion**: Simplification opportunity, edge case, minor optimization
   - **Nitpick**: Style preference, comment clarity (low priority)

2. **Provide evidence**: Show exact line/code causing the issue
3. **Suggest fix**: Offer code snippet or refactoring approach
4. **Explain why**: Why this matters and what happens if ignored

### Phase 3: Report Findings

Report ONLY findings that are either:
- **Objectively wrong** (logic error, crashes, security flaw)
- **High-impact** (perf problem, missing critical test, architectural inconsistency)

Do NOT report:
- Subjective style preferences (unless project has lint rules that enforce them)
- Single-line cleanups that don't affect readability
- Theoretical edge cases unlikely to occur in practice

**Format findings as:**
```
## [CRITICAL] Issue Name

**File**: src/auth/login.js:45  
**Issue**: Password stored in plaintext  
**Evidence**: `user.password = password;` (should be hashed)  
**Suggested Fix**:
```javascript
user.password = bcrypt.hashSync(password, 10);
```
**Why**: Passwords must be hashed. Storing plaintext is a security breach.  
**Risk if ignored**: User accounts compromised if database leaked.
```

### Phase 4: Suggest Fixes (Don't Apply)

For each finding:
1. Show the problematic code
2. Show what it should be
3. Explain the fix (1-2 sentences)
4. Do NOT modify the actual file (user decides if they want to apply it)

## Scoping Rules

**Review these files:**
- Staged files (git add)
- Modified files since last commit (git status)
- Files user explicitly names ("review src/auth.js")

**Don't review:**
- Unchanged files
- Deleted files (unless they broke something)
- Vendor code / node_modules
- Generated files (unless user asks)

## What Good Looks Like

**Good code review:**
- Finds real bugs (not hypothetical)
- Explains why it matters
- Suggests actionable fixes
- Ranked by severity (critical first)
- Aware of project patterns (matches existing style)
- Doesn't nitpick trivial things

**Weak code review:**
- Complains about style without context
- Finds issues but no fixes suggested
- All findings treated equally (not ranked)
- Doesn't understand project patterns
- Too many low-value findings (drowns out real issues)

## Integration with semantic-db-implement

This skill works standalone. However:
- If code came from semantic-db-implement skill, review will focus on implementation quality
- If code came from user edits, review will check correctness and patterns
- Can review partial implementations or work-in-progress code

The skill doesn't require semantic-db-implement to have run first—any uncommitted code can be reviewed.

## Tech-Stack Agnostic

Works with any language/framework:
- **Backend**: Node.js, Python, Go, Ruby, Java, etc.
- **Frontend**: React, Vue, Angular, etc.
- **SQL**: PostgreSQL, MySQL, etc.
- **Tests**: Jest, pytest, RSpec, etc.

The review approach is the same: understand patterns, check against best practices, rank by severity.


## Git Commit Policy

**Never add a `Co-Authored-By:` trailer to a commit message.** This applies to every commit made while this skill is active, including amends, rebases, squashes, and any commit created on the user's behalf.

- No `Co-Authored-By: Claude ...` line
- No `Co-Authored-By:` line for any other identity
- No "Generated with Claude Code" or similar attribution footer in commit messages

If a template, tool, or default instruction supplies such a trailer, strip it before committing. If an existing commit message already contains one and you are amending, remove it.
