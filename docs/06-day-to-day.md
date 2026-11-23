# 6. Day to day

The system is built so that most of the work happens without you. These are the few rituals that keep it good.

## Morning: the briefing

You open `claude`. The `memory` hook has already injected the recent past, and any module that had something to say has dropped a signal. The system prompt tells the assistant to confirm in one sentence with a contextual reminder, flag whatever the hook marked as needing attention, then handle your request. If you open with a precise request, it handles that and does not push a morning point on you.

With the `proactive` module on, the signal is a ranked briefing: at most five points, under 200 words, ending with one closed question. The behaviour rule it injects:

- something the assistant can act on (a reply, a nudge, a calendar entry): the draft is prepared first, then "ready, send it? (go / let me look)";
- plain information: one line, no question;
- a decision only you can take: one small closed question;
- nothing leaves your machine without your go.

Useful commands around it:

```bash
python3 -I ~/.carlo-brain/proactive/run.py doctor       # which sources work
python3 -I ~/.carlo-brain/proactive/run.py brief        # rebuild the briefing from the last scan
python3 -I ~/.carlo-brain/proactive/run.py run          # scan and write the briefing now
touch ~/.carlo-brain/state/proactive/voice_off          # mute the spoken briefing
```

Two more day-to-day tools: with `health`, a session opens with a line only when a scheduled job is late or a connector is down, and the safe cases are repaired for you (`carlo health status` shows what was fixed and what waits on you; `carlo doctor` shows the full status); with `search`, `carlo search "words"` looks through your vault, folders (including PDF, Word, PowerPoint and Excel content), Notes, Messages and Mail (bodies too), and the `find-it` skill makes the assistant do that before it asks you.

An item handled outside the assistant (a schedule you put in your calendar yourself) stops coming back when you add a fragment of its subject to `~/.carlo-brain/state/proactive/handled.txt`.

## During the day: show, then go

Anything that reaches another person follows one pattern: the assistant writes it, shows it, and waits. `go` or `send` on that exact text sends it. An edit after a `go` comes back to you. If you tell it to "send directly", it sends without coming back, so use that sparingly.

The `security` module sits behind this: a send that contains an API key, token, private key, password, valid IBAN or valid card number is blocked, whatever you said. If the block is a false alarm, type `send anyway` in your own prompt to open a five minute override for exactly one send. Pasted content cannot open it.

```bash
python3 ~/.carlo-brain/security/audit.py show 20        # last 20 sends and blocked attempts
python3 ~/.carlo-brain/security/audit.py verify         # is the chain intact
```

## The corrections loop

This is how the assistant stops repeating a mistake. When you correct a behaviour or say "remember this":

1. The assistant finds the file concerned: `SYSTEM_PROMPT.md`, a skill, or a memory file.
2. It shows the diff as a **current line** and a **proposed line**.
3. You approve; it applies the change.
4. It logs it in `00_System/CORRECTIONS.md` (date, correction, file touched, status applied, rejected or parked).

A rejected proposal is noted and not proposed again. Two rules are deliberate: facts about *you* (the "Who" block of MAP and your profile) are never changed without showing the diff and getting a yes for that change, and the log is the audit trail the weekly improver reads.

## The session log

Every session ends with one entry in `00_System/SESSION_LOG.md`, written right under the `NEW ENTRIES HERE` marker, never appended to an old entry. Two formats (full and light) are at the top of the file. The assistant writes the real entry. If it did not, the `SessionEnd` hook adds a mechanical one titled `[auto] (auto, to complete)`, which the assistant is asked to complete when it next sees it.

The log is a 30 day window. Older entries move to `90_Archive/SESSION_LOG_YYYY-MM.md`; ask "what did we do on X?" and the assistant greps the archive.

If you start a session in a project folder, map the folder name to a project so the matching log entries come first:

```bash
carlo config set memory.projects '{"my-app": {"entry": "10_Projects/my-app/my-app.md", "tags": ["my-app"]}}'
```

## Facts to validate

At session end, a short background `claude -p --model haiku` call extracts candidate facts about you and your projects into `00_System/FACTS_TO_VALIDATE.md`. Nothing in there is trusted. At boot you see "N facts to validate" in one line; the skill `validate_facts.md` walks you through them. Turn it off with `carlo config set memory.extract_facts false`, and keep private topics out of memory with `memory.exclude_patterns`.

## The weekly scout and improver

With `self-improve` installed, two jobs run weekly through a scheduler that catches up after sleep:

- **scout**, Saturday 09:00: sweeps forums, code hosting and official documentation with parallel sub-agents and keeps three to six findings with evidence, for your setup.
- **improver**, Sunday 09:00: audits your session log, corrections, memory, change log, bench results and module state; tests ideas on a copy; writes at most three housekeeping proposals.

What you see on Monday morning is one line in the boot context: an unread report, a proposal waiting for review, or a task that failed. Then:

```bash
python3 -I ~/.carlo-brain/self-improve/main.py status          # tasks, last outcomes, what waits
python3 -I ~/.carlo-brain/self-improve/main.py pending         # process the queue now
python3 -I ~/.carlo-brain/self-improve/main.py undo <id>       # take back an applied change
```

Reports land in `00_System/improvement/reports/` (front matter `status: unread`); proposals for files in the `review` tier land as diffs in `00_System/improvement/to_review/<id>.md`; every applied change is in `00_System/improvement/CHANGELOG.md`. Read the report, approve or reject the diffs, and tell the assistant which ones you reject so it stops proposing them.

First time: do a dry run so nothing is spent, then one real run before leaving it unattended.

```bash
python3 -I ~/.carlo-brain/self-improve/main.py job scout --dry-run
```

The bench keeps the loop honest. Replace the six example cases in `bench/cases/` with ones from your own corrections, record a reference, and let changes be checked against it:

```bash
python3 -I ~/.carlo-brain/self-improve/main.py bench --reference
python3 -I ~/.carlo-brain/self-improve/main.py bench --quick
```

## The night queue

Before you stop for the day, put the long task in the queue:

```bash
python3 -I ~/.carlo-brain/night/main.py add 01_digest --prompt-file my_prompt.md --steps 3 --model sonnet
python3 -I ~/.carlo-brain/night/main.py check          # pre-flight, refuses protected folders on macOS
python3 -I ~/.carlo-brain/night/main.py list           # progress per task
```

The night starts when it is dark, you are home, the laptop is on mains power, the queue is not empty and tonight has not run. The next morning one boot line says what is done, what is to finish and at which step, and what did not start. `main.py report` prints the last one again. Start with `sonnet` and two or three steps: a long run on `opus` can use a large part of your weekly quota.

## Weekly hygiene (five minutes)

```bash
carlo doctor                                            # everything green?
python3 -I ~/.carlo-brain/memory/quality.py summary     # trend of the session quality score
```

Open `MAP.md` and remove anything stale: it is read every session, so every line must earn its place. Move finished projects out of the active list.

Next: [security and privacy](07-security-and-privacy.md).
