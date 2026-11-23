---
name: explainer
description: "Turn a source (article, paper, PDF, web page, transcript, vault note) or a concept into a study sheet that makes the reader understand AND remember: a clear sheet with the key idea first, corrected misconceptions, source citations, recall questions and flashcards. Triggers: explain to me, make me a sheet, summarise this paper, I want to understand X, study card, revision."
---

# Explainer: understand, then remember

The goal is a sheet the reader understands and can recall a week later. Understanding comes from clear structure; remembering comes only from active recall and spacing. So every sheet ends with recall questions, cards and a review plan.

This is the lightweight version: Markdown only (Obsidian friendly), no audio or video rendering.

## Steps

1. **Source.** Read the whole source (or all the material you were given). Number the passages you may cite. If there is no source and the topic is a concept, say which claims come from general knowledge and mark them as such.
2. **Outline first.** Write the outline for yourself: the single idea the sheet teaches, the 3 to 6 sections, the vocabulary needed, the likely misconceptions. Critique it once (is each section one new idea? is anything decorative?), then write.
3. **Write `sheet.md`** with the structure below, applying the rules in `references/rules.md`.
4. **Write `cards.md`** (flashcards).
5. **Check**: every factual claim has a citation to a numbered passage or is in "Limits"; nothing is in the sheet that is not in the sources unless labelled; the sheet reads in the user's language.

## Where to put files

In the vault: `20_Knowledge/<slug>/sheet.md` and `cards.md`. Use a short lowercase slug. Keep the original source next to them (`source.md` or a link) so citations can be checked.

## Structure of `sheet.md`

```
# Title
> One sentence: what you will be able to do or explain after reading.

## In 5 lines
(five complete statements, the whole message in short)

## Words you need
(term: definition in five to ten words, in the order they are used)

## Section 1: <one idea>
Explanation in short paragraphs, then:
- Common misconception: "people think ... in fact ..." [citation]
- Check yourself: <a question that needs reasoning, not recognition>  (answer under a collapsed block or below a rule)

## Section 2 ... (repeat)

## How the pieces connect
(a list of relations with verbs: A causes B, B limits C)

## Limits
(what the sources do not say, what is contested, what is your extrapolation)

## Review plan
Day 1, day 3, day 7, day 21: answer the questions without looking; re-read only what you missed.
```

## `cards.md`

One card per line pair: `Question :: Answer` (the format of the common Obsidian spaced repetition plugins and easy to import elsewhere). 8 to 20 cards, each testing one idea, written as "why" or "what happens if" questions where possible.

## Formats beyond the sheet

If the user wants audio or a video, say that this version does not render them and offer a script for the sheet instead (a spoken outline with the same structure and recall questions). Do not claim a rendering you cannot do.

## What you hand back

The path of the sheet and the cards, the 5-line summary, and anything in "Limits" the user should know.
