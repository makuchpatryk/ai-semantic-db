---
name: semantic-db-planning
description: Create detailed implementation plans when user explicitly requests. Triggers on "plan", "design", "spec out", "let's design", "create a plan" — whenever user wants structured guidance before starting work. Produces comprehensive markdown spec covering steps, architecture, risks, trade-offs, file changes, APIs, schema, dependencies, tests, success criteria, and metrics. Explores codebase first to validate assumptions. Grills user relentlessly to zero uncertainty before planning.
compatibility: Requires Explore agent for codebase search
---

## When to Use This Skill

Use when user explicitly says: "plan X", "design X", "spec out X", "create a plan for X", "how should we implement X", "let's design X". This skill is NOT for quick answers—it's for substantial features, refactors, migrations, or architectural changes where thorough upfront planning saves dev time.

## Workflow

### Phase 1: Grill User to Zero Uncertainty

Before exploring code or writing any plan, interview user relentlessly until you have clear answers to:

- **Problem scope**: What problem does this solve? Who benefits? What's the current state?
- **Success criteria**: How do we measure if this worked? What must be true at the end?
- **Constraints**: Timeline, performance requirements, backward-compatibility needs, compliance, scope limits?
- **Unknowns**: What are the tricky parts? Where's the user uncertain?
- **Priority**: What's most important? Any hard constraints vs nice-to-haves?
- **Context**: How does this fit into existing work? Any related projects or prior attempts?
- **Technical constraints**: Database, frameworks, infrastructure limits? Existing patterns to follow?

Don't assume—**ask until you're certain**. If user gives vague answers, drill deeper. Ask follow-ups, propose scenarios, stress-test assumptions. This usually takes 5-10 questions. Stop only when you understand the problem deeply enough to spot risks and trade-offs.

### Phase 2: Explore Codebase

Use Explore agent (medium breadth) to understand:
- Project structure and naming conventions
- Relevant existing code patterns (similar features, auth patterns, data models)
- Framework/tool versions and configuration
- Existing similar implementations (to avoid reinventing)

Focus exploration on: "What exists today that's related to this task?" Not everything—just enough to make informed architectural choices.

### Phase 3: Write Comprehensive Plan

Structure the plan markdown as follows. Save to `specs/<task-name>.md`.

#### Template Structure

```markdown
# [Feature/Refactor Name] — Implementation Plan

## Summary
2-3 sentences: What problem does this solve? Why now?

## Success Criteria
Bulleted list of measurable outcomes. Must verify at the end:
- Metric 1 (specific target)
- Metric 2 (specific target)
- ... (3-5 criteria)

## Scope & Constraints
- In scope: [what this covers]
- Out of scope: [explicitly what it doesn't]
- Hard constraints: [immovable deadlines, performance targets, compliance]
- Trade-offs: [what we're prioritizing over what, and why]

## Architecture & Design

### High-Level Flow
Describe how the solution works end-to-end. Use ASCII diagram if helpful.

### Key Changes
- **File/module**: What changes. Why this choice over alternatives.
- **API changes**: New endpoints, signature changes, deprecations.
- **Data model**: Schema additions/changes. Migration strategy if needed.
- **Dependencies**: New packages, version upgrades, removals.

### Alternative Approaches Considered
For each major decision (tech choice, architecture pattern):
- Option A: pros/cons, why not chosen
- Option B: pros/cons, why chosen
- Option C: pros/cons, why not chosen

## Implementation Steps
Numbered sequence of steps from start to finish. Each step should be:
- Atomic (can be reviewed/tested independently if possible)
- Clear (specific files, functions, or behaviors)
- Ordered (later steps depend on earlier ones where relevant)

Example:
```
1. Add `profit_margin` column to database schema (migration)
2. Update ORM model to include new field
3. Add API endpoint `/products/:id/margins` 
4. Update frontend to fetch and display margins
5. Add unit tests for margin calculation
6. Add integration tests for full flow
7. Update documentation
```

### Risks & Mitigations
- Risk: [What could go wrong?]
  - Mitigation: [How do we prevent or recover from it?]
  - Mitigation: [Alternative approach if first fails]
- ... (3-5 major risks)

## Test Strategy
How do we verify this works?
- Unit tests: [what functions/behaviors]
- Integration tests: [what flows end-to-end]
- Manual testing: [scenarios to verify manually]
- Performance tests: [if applicable — what metrics]

## Success Checklist
At launch, verify:
- [ ] All success criteria met (with evidence)
- [ ] Tests passing (unit + integration)
- [ ] Code review approved
- [ ] Documentation updated
- [ ] Rollout plan (if needed) documented
- [ ] No regressions in related features

## Timeline & Estimates
- Phase 1 (implementation): ~X hours
- Phase 2 (testing): ~Y hours
- Phase 3 (review + polish): ~Z hours
- **Total**: ~X+Y+Z hours (rough estimate, plus buffer)

Note: Estimates are rough. Adjust based on your team's velocity.

## Open Questions
Any assumptions still uncertain? List them:
- [ ] Question 1?
- [ ] Question 2?
...

(These should be empty or near-empty after grilling—but if something remains genuinely unclear, call it out explicitly.)
```

## Key Principles

1. **Be specific**: Not "update auth", but "add JWT refresh-token rotation to /auth/refresh endpoint with 15-min expiry".
2. **Show trade-offs**: Explain why you chose this path over alternatives. The user should understand the reasoning, not just the decision.
3. **Flag risks early**: Better to spot problems in the plan than mid-implementation.
4. **Validate against code**: Use exploration phase to check that proposed changes align with existing patterns and won't break assumptions.
5. **Make it actionable**: Devs should be able to take the plan to implementation without major re-thinking.

## After the Plan

1. Present plan to user
2. Wait for approval, feedback, or changes
3. Revise if needed
4. Once approved: user moves to implementation (separate skill or direct coding)

Do NOT start implementing until user explicitly approves the plan.

## Example: What Good Looks Like

**Good plan** shows:
- Concrete file paths (not "update auth module", but "modify `src/auth/refresh.ts`")
- Specific API changes (endpoint URLs, request/response shapes)
- Database schema DDL or pseudo-code
- Risks that are relevant (not generic)
- Test cases tied to implementation steps
- Trade-off reasoning ("We chose approach X because Y, not approach Z because...")

**Weak plan** is vague:
- "Improve performance" without metrics
- "Refactor auth" without specifying what changes
- "Add tests" without saying which tests or why
- Risks that are too generic ("bugs might happen")
- No rationale for decisions

## Next: Implement with semantic-db-implement

After plan approval, invoke implementation skill:

```
/semantic-db-implement
```

Skill auto-discovers plan in `specs/<task-name>.md` and executes all steps.