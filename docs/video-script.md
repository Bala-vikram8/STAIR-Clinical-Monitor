# Portfolio demo recording script

Aim for a narrated screen recording lasting about two to three minutes. The words below are a script, not a claim that a video has already been recorded.

## Before recording

- Open the GitHub README, the local `reports/comparison.html` file, the linked textbook source, and the code files named below.
- Use the saved live results. Do not describe playback as a fresh API request.
- Keep credentials and environment settings off-screen. Disable notifications and enlarge the page text so it is easy to read.

## Opening — show the README

“Hi, this is STAIR Clinical Monitor, a portfolio project I built with Codex as a build partner. I wanted to compare two ways of finding a useful section in a long medical textbook.

“The project uses public OpenStax content and synthetic questions. It does not use patient records or generate medical answers.”

## Explain the approaches — show the comparison page

“The baseline splits the text into fixed, overlapping pieces and searches them using word-based vectors, called TF-IDF.

“The second method gives Claude the complete table of contents, including parent headings, and asks it to return an exact section ID and title. The code checks both against the saved source. It does not guess a replacement for an invalid choice.”

## Walk through a result — show the lung question and its source link

“This page shows a saved run of real Claude API responses. Both methods received the same five synthetic questions.

“For this question about oxygen moving from lung air sacs into blood, the baseline returned ‘Body Fluids and Fluid Compartments.’ Claude returned ‘Gas Exchange,’ which matches the section in the prepared test key.

“I can open the source link and inspect the section myself. The comparison is about finding a source section, not deciding whether a medical answer is safe.”

## Show the engineering — open the code and test record

“The main pieces are separate: chunking and vector search, the Claude section picker, and the runner that sends the same questions through both methods.

“SQLite keeps the source, settings, and returned sections so the result can be inspected later. The recorded test run has 179 passing tests, including checks for missing sources, invalid section choices, and keeping scripted replies separate from live results.”

Screen cues: `src/stair_monitor/retrieval/baseline.py`, `toc.py`, `run.py`, and `reports/handoff-tests.xml`. Show these briefly rather than reading the code line by line.

## Close — return to the results table

“On this small set, the ToC method matched all five prepared sections and the baseline matched four.

“The methods also differ in their use of Claude versus word vectors, so this does not isolate the benefit of document structure. My next evaluation would use more unseen questions and a stronger baseline that matches meaning as well as words. Those are future steps, not features I have already built.”

## Sources for the recording

The result counts, model responses, source links, and five-question scope come from the [live run](../reports/retrieval-live-results.json) and [validation record](../reports/live-comparison-checks.json), recorded on October 31, 2026. The saved test record is [handoff-tests.xml](../reports/handoff-tests.xml), dated October 31, 2026. The wording describes this development experiment only; it does not claim clinical validation or broad superiority over other retrieval systems.

Source attribution and reuse terms are recorded in [source verification](source-verification.md). No real hospital or customer use is claimed. Do not show API keys in the recording.
