# MAP: {{USER_NAME}} at a glance (injected every session)

<!-- map-template: still the template. The setup skill (type "setup" in claude) removes this line. If you edit by hand, delete this line. -->

Keep this file short. It is read at every session start, so every line must earn its place.

**Who**: {{USER_NAME}}. (Add: role, location, how you like to work, constraints such as "dictates by voice", "works in bursts in the evening".)

**Active projects** (read the entry file BEFORE working on a project):
- (Project name): one line on the goal and current state. Entry file: `10_Projects/<name>/<name>.md`.

**Upcoming deadlines**: calendar events live in your calendar, not here (they go stale). Only list deadlines that have no calendar entry.

**Where to look for more**:
- Todo list: (where you keep it).
- Contacts: (where you keep them).
- `00_System/SESSION_LOG.md`: recent sessions. Older: `90_Archive/`.
- `10_Projects/<project>/`: state and documents of each project.
- `20_Knowledge/`: reference notes you want the assistant to be able to find.
- `00_System/memory/`: behaviour rules learned over time.

**Dictation shortcuts** (if you dictate, list the words the speech-to-text gets wrong and what they mean):
- "(misheard word)" = (what you meant).
