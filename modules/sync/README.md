# sync

Keeps your vault in git, and optionally mirrored to a private remote and to a server copy, without you doing anything.

## What it does

| Hook | Effect |
|------|--------|
| SessionStart | Commits local changes, then pulls the remote (merge, no rebase). |
| SessionEnd | Commits local changes, pushes, then asks the server copy to `git pull --ff-only`. |

Both run in a detached background process, so the hook returns immediately. Without a remote the module only commits locally, which is already a free history of the vault.

If a pull conflicts, the merge is aborted, nothing is lost or overwritten, and a signal file is dropped in `~/.carlo-brain/state/boot.d/` (needs the `memory` module) so the next session tells you. Fix the conflict in the vault, then delete the signal file. It never force-pushes and never runs `reset --hard`.

## Why

A vault on one disk is one disk failure away from gone, and the same vault on two machines drifts. A commit per session is cheap and gives you history, backup and sync in one mechanism.

## Setup

```bash
carlo add sync                      # also runs `git init` in the vault if it is not a repository
```

Optional remote (use a PRIVATE repository: your vault holds your life):

```bash
git -C ~/carlo-vault remote add origin git@github.com:you/your-private-vault.git   # or:
carlo config set sync.remote git@github.com:you/your-private-vault.git
carlo config set sync.branch main
```

Optional server copy (a second machine with a clone of the same remote and working SSH keys, no password prompt):

```bash
carlo config set sync.server '{"host": "user@my-server", "path": "/home/user/carlo-vault"}'
```

Run it by hand to test: `python3 ~/.carlo-brain/sync/sync.py end` then read `~/.carlo-brain/state/logs/sync.log`.

## Customize

- `.gitignore` in the vault (a sensible default is created): add folders you never want in git.
- Commit messages are `sync: <hostname> <date>`; edit `commit_all` in `sync.py` if you want something else.

## Limits

- macOS and Linux. Scheduled sync (launchd or cron) is deliberately not included: on macOS, launchd jobs cannot read files under `~/Desktop` or `~/Documents` without extra permissions, while hooks run inside your terminal which can. Keep the vault outside protected folders if you add a scheduled job.
- Two machines editing the same note between syncs will conflict; that is reported, not auto-resolved.
- The server step only fast-forwards. If the server copy has local commits it reports `failed` in `sync.log`.
- Never put secrets in the vault. Git history keeps them forever.
