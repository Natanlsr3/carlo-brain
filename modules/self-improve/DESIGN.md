# Design notes: self-improve

Why the module looks the way it does. Each rule answers a way an unattended, self-modifying
assistant goes wrong.

## Principles

1. **Close the loop, but with a table.** An improvement system that only reports gets ignored; one that applies things itself needs hard limits. The limit is a path table evaluated by code (`tiers.py`). The model is never asked "is this risky?". It cannot argue its way into a looser tier, because it is not consulted.
2. **Strictest wins, for the whole batch.** A proposal that touches one `auto` file and one `review` file goes to review as a whole; the auto file is not applied alone. Half-applied ideas are worse than none.
3. **Unknown means review.** A path that matches no rule is never applied automatically.
4. **The protected list is in code, not config.** Anything a proposal can edit, a proposal can use to unlock itself. The settings file can add to `auto` and `review`, never lower `manual`.
5. **Do not let the judge be edited by the judged.** The bench cases sit under a manual path.
6. **Write after you can verify, restore for real.** Archive first, write atomically (temp file then rename), run the checks, and on any failure copy the archive back byte for byte, remove files the run created, and record `restored` in the journal. Undo uses hashes: if you changed the file since, it refuses unless forced.
7. **Judge the result, not the exit code.** A job that exits 0 without producing its report failed. A night step that never wrote its status line is not finished.
8. **Make the output of unattended work land in a place the model cannot corrupt.** The model writes to a scratch folder; code validates and moves it. Proposals are schema-checked before they enter the queue.
9. **Never default a score.** A judge that fails yields "not judged". A bench comparison that cannot compare (no reference, an erroring case) refuses to approve a change rather than approving by default. The judge model must differ from the tested model.
10. **Failures are loud and early.** Every failure becomes a line in the boot note at the next session. A source that cannot be read is reported, not replaced by an empty section.
11. **Catch-up beats cron.** A laptop sleeps. Compare the latest slot with the last launched slot, mark before launching, and let the machine be late within a window.
12. **Subscription, not API billing.** A background `claude -p` uses an API key if one is in the environment. Jobs strip key-like variables and use a long-lived subscription token.

## What this module does not do

- It does not let the model schedule new recurring tasks for itself; tasks live in a file you own.
- It does not apply anything to your system prompt, your settings or anything that sends messages without you reading a diff.
- It does not try to "optimise prompts" statistically. The bench measures; changes are written by a model and checked by your rules and tests.
- It does not read or write secrets, and says so in every prompt.

## Failure modes it was designed against

| Failure | Where it is handled |
|---|---|
| Edit applied, check fails, file left broken | `apply._apply_auto` restores from the archive |
| Proposal edits the tier table to unlock itself | `HARD_MANUAL` is code, `config.d/self-improve*` is manual |
| Symlink inside an auto folder pointing at a key file | `real_path` resolves before classifying |
| Job exits 0 but produced nothing | `run_job` judges the report |
| Laptop asleep at the slot | `scheduler.due_slot` catch-up within `window_h` |
| Same slot launched twice | slot written before launch, plus a lock per task |
| Judge crashes and a default score slips in | `bench.judge` returns None, status `not_judged` |
| Scheduled job bills an API key | `clean_env` strips key-like variables |
| Silent failure for days | `status.lines_for_boot` writes the boot note |
