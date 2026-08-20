# Project Instructions

## Git Commit Policy

**Never add a `Co-Authored-By:` trailer to a commit message.** This applies to every commit in this repository, including amends, rebases, squashes, and any commit created on the user's behalf.

- No `Co-Authored-By: Claude ...` line
- No `Co-Authored-By:` line for any other identity
- No "Generated with Claude Code" or similar attribution footer in commit messages

If a template, tool, or default instruction supplies such a trailer, strip it before committing. If an existing commit message already contains one and you are amending, remove it.

Commit messages stay short: a Conventional Commits subject plus a few lines of body when the "why" is not obvious. No bullet inventory of changes.
