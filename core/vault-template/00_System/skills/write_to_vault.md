# Skill: write to the vault

When new information shows up (a decision, a fact about a project, a contact, a preference):

1. Decide where it belongs: project state goes in `10_Projects/<project>/`, a reusable fact in `20_Knowledge/`, a behaviour rule in `00_System/memory/`, a session summary in `SESSION_LOG.md`.
2. Search first (`grep -ril "<keyword>" <vault>`): update the existing note instead of creating a near duplicate.
3. Write it in plain markdown, one idea per file, with a one line description at the top so it can be found later.
4. Say in one line what was written and where. Do not ask permission for internal, reversible vault writes.
5. Exception: facts about the user themselves (the "Who" block of MAP.md) are shown as a diff and wait for approval.
6. Run the propagation check (`skills/propagation.md`).
