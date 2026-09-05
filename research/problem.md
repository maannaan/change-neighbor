# Problem

Developers often edit one or two files and forget the neighbors that usually change with them:

- tests
- documentation
- configuration
- CI/CD workflows
- API contracts
- database migrations
- integration glue

Those relationships already live in the repository’s Git history: files that repeatedly appear in the same commits are likely to belong together.

Change Neighbor treats the **current uncommitted change set** as a query and the **local commit history** as evidence. V3 also reads the current diffs to infer a deterministic change intent (API route, UI, database, …) and boosts historically supported neighbors that match that intent. V4 groups that evidence into a Change Completeness Map (COVERED / REVIEW / UNKNOWN). REVIEW means “this surface often changed with similar work — inspect it.” It does not mean the change is incomplete or that a file is required.

The tool is a reminder, not an enforcer. It must stay read-only and work even when the tree is clean or the history is thin.
