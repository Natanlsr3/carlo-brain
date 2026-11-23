# Browser automation

When there is no API: log into a site, fill a form, read a page that needs JavaScript.

Platform: any. Three options, from lightest to heaviest:

## 1. Claude in Chrome (your own browser)

Anthropic's Chrome extension lets Claude drive a Chrome tab where you are already logged in. It is
the most convenient (your sessions, your cookies) and the most sensitive. Install it from the Chrome
Web Store, sign in with your claude.ai account, then check `/mcp` in Claude Code. Use a dedicated
Chrome profile for the assistant, signed in only to the sites it needs.

## 2. Playwright MCP (a separate, scriptable browser)

```
claude mcp add playwright -s user -- npx @playwright/mcp@latest
```

Runs its own browser profile, so it never touches your personal tabs. Good for forms and scraping
that do not need your logins. First run downloads a browser. Pin a version
(`@playwright/mcp@<version>`) once it works, so an update cannot change behaviour under you.
Docs: https://github.com/microsoft/playwright-mcp

One command does the registration for you (idempotent, removable, no key involved):

```
carlo connect browser                    # claude mcp add playwright -s user -- npx @playwright/mcp@latest
carlo connect browser --version 0.0.30   # pin a version you tested
carlo connect browser --status
carlo connect browser --remove
```

After it has run once, `carlo doctor` reports whether the server is still registered. Restart Claude Code, then check `/mcp`. The `browse` skill (installed by `agents-skills`) holds the rules: open and read in its own tab, never submit a form, pay, log in or enter a secret without your go. This is wiring only, not a scraping framework.

## 3. Hosted web automation (TinyFish and similar)

Claude connectors that run browser tasks in the cloud (add them in claude.ai, Settings, Connectors).
Useful for long jobs and when you do not want a browser on your machine. They are metered (check the pricing),
and your instructions and the pages visited go to that provider: do not point them at pages with
personal data.

## Rules we recommend

- The assistant works in **its own tab or profile** and never uses the windows you are typing in.
- It may open, click and validate inside that tab on its own for reversible steps. Payments, password prompts, security settings and anything that sends content to a third party stop and wait for you.
- Web pages are untrusted input and can contain instructions aimed at the assistant. Do not give it write tools in other connectors during a browsing session on unknown sites.
- Two attempts per method, then change method (script, then a visible click, then local files, then the server or the web).
