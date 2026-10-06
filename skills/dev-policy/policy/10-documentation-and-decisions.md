# 10 — Documentation and decisions

Applies whenever a change alters what a reader (human or agent) needs to know: architecture, contracts, operations, decisions, risks. Documentation is code: it ships in the same change, it is reviewed, and it can be wrong in the same way code can.

Contents: 1 Same change, same commit · 2 One document, one purpose · 3 Decisions · 4 Risks · 5 Plans · 6 Documentation for agents · 7 Comments in code · 8 Keeping docs true · 9 Sources

## 1. Same change, same commit

**DOC-01** MUST update the documentation that a change invalidates in the same commit as the change. A stale claim misleads more than a missing one, and an agent reading it will act on it.

**DOC-02** MUST write documentation for the reader who was not there: what it is, why it is shaped this way, how to operate it. The change narrative ("we refactored…") belongs in the commit message, not the document.

## 2. One document, one purpose

**DOC-03** MUST keep each long-lived document single-purpose and named for that purpose: a runbook, a risk register, a decision record, an architecture description, a setup guide. Never grow one into another ("the runbook that also holds the register").

**DOC-04** SHOULD organise reference material along Diátaxis lines (tutorials, how-to guides, reference, explanation) and keep each type separate; a how-to that stops to explain history is neither.

**DOC-05** MUST keep an orientation index (the project's root instruction file) that says which document to read for which task, in a table, and nothing else at length.

## 3. Decisions

**DOC-06** MUST record every decision a later reader would otherwise re-derive: the context, the choice, the alternatives rejected and why, the date. One decision record per repository (or one file per decision in an `adr/` folder) with stable ids; entries are never edited after the fact, only superseded by a new entry that links back.

**DOC-07** MUST reference the decision id from the code it shaped (`// DL-012: …`) where the choice is non-obvious at the point of reading.

**DOC-08** MUST record a decision in the same change that makes it. A decision that exists only in a plan, a conversation or a planning artefact is lost when the plan is deleted.

## 4. Risks

**DOC-09** MUST keep one accepted-risk register per repository. Each entry: id, the risk, what it means in practice, who accepted it and when, and the condition that **reopens** it. A risk recorded only in a plan is not accepted; it is forgotten.

**DOC-10** MUST reference the risk id from code, issues and runbooks that work around it, and review the register whenever a reopen condition plausibly occurred and before any customer commitment.

## 5. Plans

**DOC-11** MUST treat a plan as a working document with an end date: it carries a tracking issue and a review-by date, and it is deleted when the work finishes. Its decisions go to the decision record, its carried gaps to the risk register, its leftovers to issues. Finished plans with stale status lines are the main source of misleading documentation.

**DOC-12** MUST NOT keep generated planning artefacts (diff bundles, state files) in the repository once merged; git history already holds the result.

## 6. Documentation for agents

**DOC-13** MUST keep always-loaded instruction files short (well under 200 lines) and specific: commands, hard rules, conventions that are not standard, and a table of where to read more. For each line ask: would removing it cause a mistake? If not, remove it.

**DOC-14** MUST put procedures longer than a few lines in a skill or reference file loaded on demand, not in the always-loaded file. Imports do not reduce context cost; they only move it.

**DOC-15** SHOULD follow the index/knowledge split in `~/.claude/conventions/documentation.md`: an index file says *what* is here and *when* to read it; a knowledge file holds only what cannot be learned from the code (rationale, invariants, trade-offs).

**DOC-16** MUST convert any instruction that must happen every time into a hook or a deny rule. Instruction text is context, not enforcement; it can be lost at compaction or ignored.

**DOC-17** MUST NOT describe work as "in progress", "not yet", "planned" anywhere it will be read by an agent unless it is still true today, with an absolute date.

## 7. Comments in code

**DOC-18** MUST follow `02-code-quality.md` CODE-08 to CODE-11: why not what, timeless present, explanation blocks for non-trivial functions, "use when" triggers on public APIs.

## 8. Keeping docs true

**DOC-19** SHOULD check mechanically what can be checked: paths, commands, migration names and environment variables named in documents exist; links resolve; counts that drift are recomputed, not restated.

**DOC-20** MUST run that check after any move, rename or delete of a documented file, and repair every reference in the same change.

## 9. Sources

- Documenting architecture decisions, Nygard (2011): https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
- ADR organisation: https://adr.github.io/
- Diátaxis: https://diataxis.fr/
- Claude Code memory and CLAUDE.md guidance: https://code.claude.com/docs/en/memory
- Claude Code best practices: https://code.claude.com/docs/en/best-practices
- AGENTS.md convention (2025): https://agents.md/
- Context files and agent performance, Gloaguen et al. (2026): https://arxiv.org/abs/2602.11988
