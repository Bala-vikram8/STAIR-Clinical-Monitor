# Public source verification

Updated on October 31, 2026. Public textbook text only; no patient data, hospital deployment, or clinical review is claimed.

## Current result: OpenStax imported

The user selected **OpenStax, Anatomy and Physiology 2e** as the primary source. Its complete publisher contents list and every linked section's textual body are now stored in SQLite. This is an educational textbook, not a treatment guideline.

The [dated import check](../reports/openstax-import-checks.json) records the database queries, source hash, repeat-import check, and tests. The [complete resolved contents](../reports/openstax-complete-toc.json) lists every title, parent path, source link, and saved section ID.

| Item | Stored result |
| --- | --- |
| Publisher | OpenStax, Rice University |
| Official source | https://github.com/openstax/osbooks-anatomy-physiology |
| Fixed revision | `5ae32b3f4bc24ed003e91dc38bf47dba80751044` |
| Publication-date label | **unknown – publisher content** |
| Date field | Empty (`NULL`), with the exact label saved in `publication_date_note`; no year guessed from file dates |
| Source type | Open textbook; not a treatment guideline |
| Licence | CC BY-NC-SA 4.0; retain attribution, noncommercial use, same terms for adaptations, and item-specific notices |
| Complete source snapshots | 1 |
| Text-bearing sections | 198 |
| Part and chapter heading rows | 34 |
| Rows in `sections` | 232 |
| Rows in `toc_entries` | 232 |
| Missing section files or unresolved titles | 0 |

These counts come from the saved SQLite source on October 31, 2026, not from a planned target. The database also retains the earlier CDC candidate addresses, making 3 rows in `guidelines`; only OpenStax has a stored source snapshot.

Five sample section titles, read from the database:

- Preface
- Introduction
- Overview of Anatomy and Physiology
- Structural Organization of the Human Body
- Functions of Human Life

## What was downloaded and checked

The publisher's [contents file](https://raw.githubusercontent.com/openstax/osbooks-anatomy-physiology/5ae32b3f4bc24ed003e91dc38bf47dba80751044/collections/anatomy-and-physiology-2e.collection.xml), README, LICENSE, and all 198 linked section XML files were downloaded from the fixed official source revision. Every file has a recorded UTC time, address, and hash. Earlier successful small downloads were reused only after their hashes were checked. CDC and WHO were not requested again.

The publisher collection has 6 top-level parts and 34 named groups in total. Module titles were resolved from their original section files. Repeated titles retain distinct IDs and full parent paths. The earlier [partial hierarchy](../reports/openstax-anatomy-hierarchy.json) and [source check](../reports/openstax-anatomy-access.json) are historical records from October 30, 2026; the new complete contents file supersedes their unresolved-title status.

All source files are included in a deterministic ZIP stored locally and inside the database. The ZIP's hash, file count, and original bytes were checked against the saved snapshot. Repeating the import reuses the same source snapshot and does not add duplicate sections.

The parser keeps paragraphs, nested headings, lists, review questions and solutions, tables, footnotes, glossary entries, mathematical scripts, captions, image descriptions, and original links. The import check found no missing source text fragments under its documented whitespace-normalized text-presence check. That check does not prove medical correctness or perfect interpretation of a formula.

**Limits:** image binaries and linked videos were not downloaded. Their available descriptions, captions, and source references remain in the text. Questions that need unseen visual details cannot be treated as supported by this text-only corpus. Source completeness is not a claim that the edition is current or safe for clinical care.

## Source dates and storage rules

The publication date is explicitly **unknown – publisher content**, as requested. The date value stays empty to avoid placing a label in a field reserved for calendar dates. The label and the reason are saved with the source snapshot and shown by the status command.

Parent parts and chapters store their own heading text only. Each linked module stores its full original title and rendered body, including its internal subheadings. Child bodies are not repeated inside parent rows. Text offsets count characters in the exact saved normalized text, not bytes or model tokens.

The table name `guidelines` is retained from the initial schema; its OpenStax row is explicitly labelled as a textbook. Source verification records a successful public text import, not a clinician's endorsement.

## Historical CDC failures and paused sources

CDC downloads remain paused by user instruction. No CDC request was made during the alternative-source check or this import.

| Candidate address | Actual earlier result |
| --- | --- |
| https://www.cdc.gov/sti/hcp/treatment-guidelines/index.html | The request failed at the proxy connection before the guideline page was downloaded |
| https://www.cdc.gov/mmwr/volumes/71/rr/rr7103a1.htm | Not requested: the earlier command used `&&` and stopped when STI failed. There is no separate opioid error to quote |

The first STI command printed exactly:

```text
curl: (22) The requested URL returned error: 403
STI HTTP 000
```

The earlier diagnostic request printed:

```text
curl: (56) CONNECT tunnel failed, response 403
```

Retained response headers included:

```text
HTTP/1.1 403 Forbidden
content-length: 16
content-type: text/plain
server: envoy
```

The `000` is curl's missing destination status, not a CDC response code. The earlier summary that suggested two separately failed CDC requests was too broad. CDC publication dates and contents remain unverified; no CDC snapshot or section body is stored.

## Historical WHO checks

These checks were made on October 30, 2026. They were not retried during the import.

| Source URL | Actual result | Decision |
| --- | --- | --- |
| https://iris.who.int/handle/10665/352754 | `curl: (56) CONNECT tunnel failed, response 403`; header `HTTP/1.1 403 Forbidden` | Blocked; no title, publication date, or contents verified |
| https://www.who.int/publications/i/item/9789240049338 | Same exact proxy error and header | Blocked; no title, publication date, or contents verified |
| https://raw.githubusercontent.com/WorldHealthOrganization/smart-hiv/main/README.md | HTTP 200 for the README | Reachable technical implementation framework; not accepted as a full clinical guideline corpus |

The [historical access record](../reports/source-access-2026-10-30.json) preserves these observations. The WHO technical README is not being described as a blocked source or an imported guideline.

## Checks and stopping point

The [test record](../reports/openstax-import-tests.xml) and dated import check record passing offline parser, downloader, migration, and import tests. SQLite integrity, parent links, contents references, source hashes, complete module coverage, exact text positions, and repeat import were checked against the actual stored source.

The approved ToC and text-import milestone is complete. At that checkpoint work stopped before retrieval, with no paid API calls. The user later approved retrieval methods and synthetic paired tests; see the [retrieval guide](retrieval.md) for that separate work and its live API blocker. No source snapshot was changed by retrieval. Dashboard work still requires the user's next approval.
