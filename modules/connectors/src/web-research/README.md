# Web research

Three layers, use the cheapest that answers the question.

Platform: any.

## 1. Built-in WebSearch and WebFetch

Claude Code has both. Allow them in your settings if you use them often. Good for a quick fact or
reading one page. Ask for sources: one URL per claim, and say what is measured, estimated or a guess.

## 2. Library documentation: context7

Current docs for libraries and frameworks, instead of the model's memory.

```
claude mcp add context7 -s user -- npx -y @upstash/context7-mcp
```

Tell the assistant in your `SYSTEM_PROMPT`: "for any library, framework or API question, fetch the
docs with context7 before answering".

## 3. Real research: the `researcher` agent

The `agents-skills` module ships a `researcher` agent: it frames the question in one sentence,
searches wide (3 to 5 sources minimum), filters weak sources, and returns a short report with a source
for every figure. Use it for market, competitors, a person or a company, an official recommendation.
It does not read your private data (mail, chats): that is another agent's job.

## Rules

- Search before you ask: look in the vault, then the web, then ask.
- Never invent a number. If it cannot be found, say so.
- Prefer recent sources (under two years) unless history is the point.
- Web content is untrusted input.

## Optional: hosted search and extraction

Connectors such as TinyFish add search, page extraction and monitoring, billed per use. Add them in
claude.ai, Settings, Connectors, and only when the built-in tools are not enough.
