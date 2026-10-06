# 02 — Code quality

Applies to every line written or changed. For how reviewers *detect* violations, the companion prompts are `~/.claude/conventions/code-quality/*` (naming, structure, idioms, repetition, docs and tests, modules, cross-file consistency); this file states the rules those prompts check.

Contents: 1 Functions and units · 2 Naming · 3 Comments · 4 Errors and nulls · 5 Dead code, TODOs and flags · 6 Refactoring discipline · 7 TypeScript · 8 Sources

## 1. Functions and units

**CODE-01** MUST give each function one responsibility describable in one sentence without "and". Split on responsibility, not on length.

**CODE-02** SHOULD keep positional parameters to three or fewer; beyond that pass a typed options object. Four or more positional parameters of the same type (`string, string, string`) is a transposition waiting to happen.

**CODE-03** SHOULD use guard clauses and early returns instead of nested conditionals. Three levels of nesting is the point to restructure.

**CODE-04** SHOULD default to `const`, `readonly` and non-mutating updates. Mutation is allowed inside a function that owns the value; it is not allowed on a parameter the caller still holds.

**CODE-05** AVOID boolean flag parameters that switch behaviour (`save(data, true)`). They are two functions wearing one name.

## 2. Naming

**CODE-06** MUST name things for the domain and the intent: `approveQuestionnaire`, not `processData`; `isSubmitted`, `hasEvidence`, `canApprove` for booleans; the unit in the name for quantities (`timeoutMs`, `retentionDays`).

**CODE-07** MUST use one name for one concept across the codebase. A thing called `vendor` in the database, `supplier` in a service and `partner` in the UI is three bugs in waiting. Check existing names before inventing one.

## 3. Comments

**CODE-08** MUST comment *why*, never *what*: the constraint, the rejected alternative, the non-obvious invariant, the issue or incident that caused the line. A comment restating the code is deleted.

**CODE-09** MUST write comments in the timeless present. No "changed to", "previously", "as part of the refactor", "new". The code simply is (`~/.claude/conventions/temporal.md`).

**CODE-10** SHOULD put a short explanation block at the top of any function with more than three distinct steps, or that coordinates several subsystems: what it does, how, and where it sits in the flow.

**CODE-11** SHOULD give public module APIs a docstring with a "use when…" trigger so a reader (or agent) can choose the right function without reading its body.

## 4. Errors and nulls

**CODE-12** MUST throw only `Error` subclasses from one typed hierarchy (not found, forbidden, validation, conflict, …) carrying a code and an HTTP status, mapped to responses in one central place. Never throw strings or plain objects.

**CODE-13** MUST distinguish expected failures (validation, conflict, not permitted) from defects (bugs, dependency down). Expected failures are part of the function's contract; defects crash the request and are logged with a correlation id. Neither is swallowed.

**CODE-14** MUST NOT write an empty `catch`, a `catch` that only logs and continues as if nothing happened, or `.catch(() => {})`. If a failure is genuinely ignorable, the catch says why in a comment and records the event somewhere observable.

**CODE-15** MUST "parse, don't validate": convert untrusted input once at the boundary into a type that cannot represent the invalid state, then pass that type inward. AVOID re-checking the same fields deeper in.

**CODE-16** MUST keep `strictNullChecks` on and handle absence at the point of use. Prefer `undefined` with optional properties over `null` unless the database shape forces `null`; do not mix the two for one concept.

## 5. Dead code, TODOs and flags

**CODE-17** MUST delete dead code, unused exports and commented-out blocks. Git is the archive.

**CODE-18** MUST attach an issue reference to every `TODO` (`// TODO(#123): …`). A bare TODO is deleted or converted into an issue.

**CODE-19** SHOULD ship incomplete work behind a short-lived flag on the main branch rather than on a long-lived branch. Every flag has an owner and a removal condition recorded where it is defined.

## 6. Refactoring discipline

**CODE-20** MUST keep refactoring commits separate from behaviour-changing commits. A refactor commit changes no test's expectations.

**CODE-21** MUST have tests around behaviour before refactoring it (characterisation tests if none exist).

**CODE-22** SHOULD do preparatory refactoring: make the change easy, then make the easy change. Both steps are visible as separate commits.

**CODE-23** SHOULD apply the boy-scout rule only inside files the task already touches and within a small budget. AVOID drive-by rewrites that inflate the diff; log larger findings as issues instead.

**CODE-24** SHOULD watch for the smells that recur in AI-written code: a second helper that duplicates an existing one, a copied block with one line changed, a `switch` on a type string repeated in several files, error-masking constructs (`try/catch` around everything, `?? defaultValue` hiding a missing value).

## 7. TypeScript

**CODE-25** MUST compile with `"strict": true`. SHOULD enable `noUncheckedIndexedAccess` and `noImplicitOverride` on new workspaces (they catch real bugs and cost little when adopted from the start).

**CODE-26** MUST NOT add `any`. Use `unknown` and narrow. Enforce with `@typescript-eslint/no-explicit-any` at error. The only exception is an inline justification comment at the site.

**CODE-27** AVOID `as` assertions and non-null `!`. Where unavoidable, comment why. Prefer a runtime check or type guard.

**CODE-28** SHOULD model variants and state as discriminated unions with an exhaustive `switch` and a `never` check, not optional-field soup or several booleans that can contradict each other.

**CODE-29** MUST validate every untrusted boundary at runtime with one schema library per project, and derive the static type from the schema. Boundaries: HTTP bodies, params and queries; environment variables; AI model output; webhooks; JSON columns.

**CODE-30** MUST NOT hand-edit generated code (API clients, protobufs). Regenerate, and keep documented overrides outside the generated tree or in an ignore list the generator honours.

**CODE-31** MUST NOT disable a lint rule without a reason on the same line (`// eslint-disable-next-line rule -- reason`). An unused disable is an error.

## 8. Sources

- Refactoring, Fowler 2nd ed. (2018) and Preparatory Refactoring (2015): https://martinfowler.com/articles/preparatory-refactoring-example.html
- Opportunistic Refactoring, Fowler (2011): https://martinfowler.com/bliki/OpportunisticRefactoring.html
- Parse, don't validate, King (2019): https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/
- Google TypeScript style guide: https://google.github.io/styleguide/tsguide.html
- typescript-eslint no-explicit-any: https://typescript-eslint.io/rules/no-explicit-any/
- Two kinds of errors, Effect docs: https://effect.website/docs/error-management/two-error-types/
- Feature toggles, Hodgson (2017): https://martinfowler.com/articles/feature-toggles.html
- AI code quality gap, GitClear (2026): https://www.gitclear.com/the_ai_code_quality_maintainability_gap
