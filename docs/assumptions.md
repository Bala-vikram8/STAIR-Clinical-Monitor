# Assumptions and decisions

Updated on October 31, 2026. Choices, assumptions, and checked outcomes are distinguished below. The current source-import evidence is in [the dated check record](../reports/openstax-import-checks.json). Do not silently turn an assumption into a result.

| Topic | Current assumption or decision | Reason and limit |
| --- | --- | --- |
| Approval | The user approved live Claude retrieval and the comparison view after the implementation checkpoint | That work is complete. This does not authorize answer generation, a held-out final benchmark, or clinical deployment |
| Existing repository | The starting checkout contains only a README | Local inspection on October 30, 2026 found no application, dependency files, or tests |
| Project purpose | This is a local portfolio experiment, not a clinical service | No hospital, customer, deployment, or clinical validation is claimed |
| Name | “STAIR-inspired” describes table-of-contents selection | No STAIR paper or exact reproduction method was supplied; do not imply one |
| First sources | CDC sources are paused; investigate reachable public alternatives | The user directed this change on October 30, 2026. No further CDC retries. The previous chained command never requested the opioid page |
| Alternative source type | The user selected OpenStax anatomy as the primary source | Educational textbook, not a treatment guideline. Later questions must fit this source rather than assume it supports treatment advice |
| Evidence checkpoint | The source and import checks were shown before retrieval was approved | The next checkpoint shows retrieval code structure and five development test results, with live and scripted outcomes distinguished |
| Stored corpus | The complete publisher contents list and all linked textual bodies are stored | Shared unchanged by both retrieval methods. Images and linked videos remain external |
| Update cadence | No common yearly update schedule is assumed | The prompt's claim about yearly CDC diabetes updates has not been established. Verify each guideline's own dates and update history |
| Public access | Publicly readable does not automatically mean unrestricted reuse | Record publisher terms and attribution before accepting a source |
| Freshness | Experiments use fixed, dated copies | Repeatable comparison needs stable inputs. A saved copy may become outdated and is not care advice |
| Source structure | OpenStax has a publisher collection tree with part/chapter groups and module links | Every module title was resolved from its linked file; the complete tree and bodies are stored. CDC structure remains unverified |
| Section ownership | Groups keep heading text; each module keeps its full body and inline internal headings | No child module body is repeated in a parent. Tables, notes, glossary entries, and mathematical notation are preserved in rendered text |
| Coordinates | Section offsets count Python text characters, not bytes or model tokens | Normalized text is saved with the parser version. Later chunk token positions must not be confused with these source offsets |
| Versions | Original bytes and parsed text are saved together; a changed parser gets a new version | A deterministic source ZIP and its hash identify the complete file set. Reimport was checked to retain the same snapshot and row counts |
| Source dates | OpenStax's publication date is “unknown – publisher content” | Date field is NULL; the exact label is in publication_date_note. No revision, file, or download date is used as a book publication date |
| Text-only scope | Images and linked videos are not imported as binary files | Captions, alt text, and source paths remain. Later questions must not depend on unseen visuals |
| Language | Start with English source text and synthetic questions | Other languages need separate source and question review |
| Questions | The demo offers reviewed synthetic questions only | No free-text patient stories, uploads, or patient data belong in this project |
| Main task | Main test questions require a single source section | Multi-section questions need separate scoring and will be labelled as an extension |
| Answer key | Accepted sections and evidence passages are prepared before final runs | The section picker and answer writer must never receive this key |
| Baseline | Use fixed overlapping body-text windows and local TF-IDF word vectors | Explicit lexical vector baseline with cosine search. It is not a neural embedding comparison; do not generalize its results to every RAG system |
| Cross-boundary chunks | Attribute the top chunk to the section with the most overlapping tokens; ties use document order | Makes section scoring explicit. Preserve every overlap and the actual retrieved text so the rule's limits remain visible |
| Search scale | SQLite-stored vectors and direct similarity search should fit the initial corpus | Confirm corpus size and resources before choosing a model. Revisit if measured scale requires it |
| Vector settings | Fixed word windows, overlap, vocabulary, weights, and locked library versions are recorded | Settings were chosen before running the development fixture. No external neural model weights are used |
| Claude | The user selected claude-opus-5-5 and real source choices were returned by that exact model ID | Section selection only. The temperature field is omitted after an actual API rejection; provider defaults apply. No answer generation |
| ToC input | The complete source ToC fits the configured prompt budget in the successful live run | Exact provider counts and the full entry count are saved per question. A future over-budget request still stops without dropping headings |
| Exact selection | Claude returns a matching section title and ID, or refuses | Repeated titles need full paths. Unknown or mismatched choices are failures, not guesses to repair silently |
| Shared answer writer | Both methods use the same model, prompt, generation settings, and source-text budget | Evidence differs by design. Record actual inputs, limits, and any shortening |
| Missing support | Insufficient evidence leads to a refusal or explicit limitation | No inferred dosage, treatment, or patient-specific recommendation is allowed to fill a gap |
| Faithfulness review | A human review is needed for reported faithfulness | Codex is not a clinician. If no human review occurs, leave that result unreviewed; do not fabricate approval |
| No clinical validation | Faithfulness does not establish medical correctness or safety | A claim can match an old source and still be unsuitable for care |
| Development tests | A small synthetic fixture and fixed retrieval settings exercise the code | Not a held-out benchmark. Scripted ToC replies are test doubles, never evidence that Claude found the right section |
| Results and provenance | Save the same questions and each method's actual outcome together | Live, scripted, selected, no-match, invalid, blocked, and error states remain distinguishable; no missing prediction is filled from the answer key |
| Randomness | Saved model IDs and settings do not guarantee identical future API answers | Keep exact responses and run times. Record repeated runs separately if used |
| Interface | FastAPI with a simple HTML results page is the default | The user allowed HTML or Streamlit. HTML avoids adding another running service |
| API secrets | Credentials may be absent; presence is checked before asking | Stage A environment metadata reports no secret bindings. Recheck securely in the stage that needs the API; never save secret values in code or chat |
| Network | Official sources and model/API hosts may need allowed-domain additions | Stage A metadata reports restricted access with package presets only. Verify actual requests and preserve existing rules if configuration is later needed |
| Spending | No live API spending occurs during design or this storage stage | Before a later live check, document the chosen model and a bounded run plan; comparisons must not launch an unbounded job |
| Offline tests | Test fixtures and API substitutes can validate logic without paid calls | Passing them does not establish live model quality. Report live, offline, skipped, and unrun checks separately |
| README numbers | Every future number requires a source and date | Measured results link to dated run records; software requirements link to their documented source. Planning text currently avoids numerical claims in the README |
| Build partner | Codex is named openly as the build partner | This is attribution, not a claim of medical review |

## Still to settle in the relevant stage

- CDC and WHO remain documented blocked or unsuitable sources; no retries were made. The selected OpenStax text-import milestone is complete. It is not a clinical review or proof of currency.
- Live Claude access and full-prompt counts have now been verified for the saved development run. Future model or source changes still need their own recorded validation.
- Question counts, development/final split, accepted sections, final settings, and the written claim-review guide: stage D, before the final run.
- Human claim review: complete it for reported faithfulness, or clearly leave the result unreviewed. This does not stop independent retrieval measurement.

Only user approval can move work into the next stage. An unanswered question or a saved document does not count as approval.
