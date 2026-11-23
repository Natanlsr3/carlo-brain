# search

`carlo search "<words>"`: a local, read-only search over your whole computer, plus a skill (`find-it`) so the
assistant looks before it asks you. Results are `path:line: snippet`, capped.

Status: **beta**. Tested on temporary folders, a simulated Mail index, tiny real docx, xlsx, pptx and emlx fixtures, and a mocked `pdftotext`. Apple Notes and Messages go
through the `connectors` readers, which depend on private file layouts that can change; none of it was run on real personal data.

## Why

"I could not find it" is usually "I did not look in the right place". The order is fixed so the cheap and
reliable places come first: your vault, then your folders, then your chats and mail.

## Setup

```bash
carlo add search
carlo search "invoice march"
carlo search "budget" --source vault,folders --max 10
carlo search "dentist" --source notes,messages,mail
carlo search "contract" --spotlight        # also asks Spotlight (macOS), paths only
carlo search "plan" --json
carlo search --rebuild-cache               # empty and refill the optional text cache (see below)
```

Install writes `~/.carlo-brain/config.d/search.json` (never overwrites) and the skill `~/.claude/skills/find-it/SKILL.md`
(never overwrites yours: ours is saved as `SKILL.md.new`). Exit code 0 with results, 1 without.

## What it searches, in order

1. **vault**: the folder from `config.json`, text files and documents, most recently modified first.
2. **folders**: `folders` of the config (default `~/Documents`, `~/Desktop`, `~/Downloads`). Besides text files, it reads inside documents (next section).
3. **notes** and **messages** (macOS): the `connectors` Apple readers (`notes.py search`, `messages.py search`), read-only. Needs the `connectors` module and Full Disk Access.
4. **mail** (macOS): subject and sender in Apple Mail's local index, then message bodies from the `.emlx` files, both opened read-only. Sent mail is included; Trash, Junk and Drafts are skipped. A hit on a body is the path of the `.emlx` file and the line in the message (headers first, then the body).
5. **spotlight** (opt in with `--spotlight`, macOS): `mdfind` on your folders. Paths only.

Matching is case and accent insensitive; every word of the query must be on the same line. A file whose
name matches is reported with line 0.

## Inside documents and mail

| Type | How it is read |
|---|---|
| PDF | `pdftotext` if installed, else macOS `mdimport -t -d2`, else the Spotlight text (`mdls`), else only the file name matches |
| `.docx`, `.pptx`, `.xlsx` | `zipfile` plus text pulled out of the XML with regular expressions (no XML parser, so no entity bombs); an archive that expands past 4 times the size cap is refused. Excel: one line per row, cells joined with ` | ` |
| Mail `.emlx` | stdlib `email` module, plain text preferred, otherwise HTML with tags, style and scripts removed. A small local reader: the `proactive` module has one too, but importing it would couple two modules that install separately |

Documents are read after the plain text files, newest first, so they cannot use up the walk's time. A line inside
a document that looks like a secret is dropped before matching, so it is never shown and never cached. The line
number of a document hit is a line of the extracted text (paragraph, slide or row), not a page.

**Optional cache.** Extracting a PDF costs a process per file. With `"cache": true` (or after `carlo search --rebuild-cache`)
the extracted, already redacted text of documents is kept in `~/.carlo-brain/state/search-cache/`, one `.json` per file
(mode 600, folder 700), keyed by path and checked against modification time and size, so an edited file is read again.
It stops growing at `cache_max_mb` (200). `--rebuild-cache` empties it and refills it from the vault and folders, then
searches if you gave words. The cache is off by default: it is a second copy of your documents' text on disk. Delete the folder to remove it.

## Safety

- **Read only.** Nothing is written, moved or sent. A test checks the folder tree is unchanged after a search.
- **Deny list, always on**: folders `.ssh`, `.gnupg`, `.aws`, `.git`, `Library`, `keys`, `secrets`, `node_modules`, virtual environments, caches; files `.env*`, `*.pem`, `*.key`, `id_rsa*`, `*token*`, `*secret*`, `*password*`, `*credential*`, key stores, shell profiles and histories. Your config adds to it (`deny_dirs`, `deny_files`), it cannot remove from it. It applies to Spotlight results too. A vault that lives inside a `Library` folder (iCloud) is still searched, because you named it.
- **Skipped**: binary files, text files over `max_file_kb` (1 MB), documents over `max_doc_mb` (20 MB), mail files over `max_mail_kb` (4 MB), hidden folders.
- **A line that looks like a secret** (API key, private key header, `password = ...`) is replaced by a placeholder, never printed.
- **Caps**: `max_results` (30) in total, `max_per_file` (3). Time: `time_budget_s` (20 s) for the walk, and the same again for reading inside documents and mail bodies (40 s at most in all).
- **Read only.** The one thing written is the opt-in cache, which holds redacted text. A mail body can still hold a secret in a line that does not look like one: use `"deep": false` to turn off reading inside documents and mail.

## Customize

```json
{"folders": ["~/Documents", "~/Projects"], "deny_dirs": ["private"], "deny_files": ["*.bak"],
 "max_results": 30, "max_per_file": 3, "max_file_kb": 1024, "time_budget_s": 20,
 "deep": true, "max_doc_mb": 20, "max_mail_kb": 4096, "cache": false, "cache_max_mb": 200}
```

## Limits

- Not read: images and scans (no OCR; a PDF with no text layer matches by file name only), old `.doc`, `.ppt`, `.xls`, Pages, Numbers, Keynote, mail attachments and WhatsApp (it has its own MCP server in `connectors`).
- Still no index and no semantic search: each search walks the folders and reads documents one by one. The cache saves the extraction, not the walk. Fine for thousands of files, slow for millions; a mailbox of hundreds of thousands of messages will hit the time budget and return only the newest.
- Mail bodies: Apple Mail only, and only messages whose `.emlx` is on disk (Mail may keep older ones online only). Encrypted or S/MIME mail is not readable.
- Excel: values as stored (a formula shows its last result, dates show as serial numbers). A password protected Office file is skipped.
- `mdimport` and `mdls` output formats are macOS internals; the Spotlight fallback is tested with mocks only.
- Linux: vault and folders only (PDF needs `pdftotext`).
