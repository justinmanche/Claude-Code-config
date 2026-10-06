# 00 — Principles

How to think about any design or code decision before the specific sections apply. These are heuristics with known failure modes, not laws; each rule says what it protects against.

Contents: 1 Order of priorities · 2 Duplication and abstraction · 3 Speculation · 4 Simplicity · 5 Object-oriented principles in TypeScript · 6 Depth over fragmentation · 7 Boring technology · 8 Sources

## 1. Order of priorities

**PRIN-01** MUST, when two goods conflict, resolve them in this order: it works (tests pass and the user-visible behaviour is right) → it reveals intent → it has no duplicated knowledge → it has the fewest moving parts. This is Kent Beck's ordering. _Why:_ most over-engineering comes from optimising the third and fourth before the first two are secure.

**PRIN-02** MUST treat "it works" as proven at the layer the user touches, not at the inner function that was edited. A unit test is necessary, never sufficient (see `06-testing.md`, TEST-30).

## 2. Duplication and abstraction

**PRIN-03** MUST read DRY as "one authoritative source for each piece of **knowledge**" (a business rule, a limit, a schema), not "no two similar-looking blocks". Two functions that look alike but encode different decisions are not a violation; one rule stated in two places is.

**PRIN-04** MUST NOT extract a shared abstraction before the third real occurrence (rule of three). Before that, duplication is cheaper than guessing the abstraction wrong.

**PRIN-05** AVOID adding a parameter or boolean flag so an existing helper can serve one more caller. That is the signature of the wrong abstraction. Inline it back into the callers and re-extract what is actually common.

_Example:_ `formatInvoiceDate()` and `formatAuditDate()` may share one implementation today. They answer to different requirements; keep them separate until a single rule demonstrably governs both.

## 3. Speculation

**PRIN-06** MUST NOT build for a requirement no current story needs: configuration options nobody sets, extension points with one implementation, generic repositories, plugin systems, "future-proof" abstractions. Build it when it is needed; it will be cheaper then because you will know the shape.

**PRIN-07** YAGNI does not excuse skipping the work that keeps code easy to change later: tests, clear names, small modules, and recording the decision. Those are not speculation.

## 4. Simplicity

**PRIN-08** SHOULD choose the simplest design that passes the tests and reveals intent. Complexity must be paid for by a concrete problem it solves now. "Might scale better" is not a problem.

**PRIN-09** MUST prefer the solution a future reader with no context can follow over the clever one. The reader is usually an AI agent or you in six months; neither remembers why.

## 5. Object-oriented principles in TypeScript

**PRIN-10** SHOULD apply SOLID as questions, not as a compliance checklist:
- Single responsibility: can I describe this unit in one sentence without "and"?
- Open/closed: do I keep changing this file for unrelated reasons?
- Liskov: can a caller swap implementations without surprises?
- Interface segregation: does a consumer depend on methods it never calls?
- Dependency inversion: does domain logic import the database driver or the web framework?

**PRIN-11** In TypeScript a function plus a structural type usually replaces an interface-per-class, a dependency-injection container, or an inheritance hierarchy. AVOID introducing those unless two real implementations exist.

**PRIN-12** SHOULD prefer composition over inheritance everywhere. Inheritance couples children to parent internals; composition couples to a narrow interface.

## 6. Depth over fragmentation

**PRIN-13** SHOULD write "deep" units: a small, simple interface hiding substantial logic. AVOID the opposite, where a reader must open five two-line functions to understand one operation. Function length is not the smell; unclear responsibility is.

**PRIN-14** SHOULD keep side effects (database, network, clock, randomness) at the edges and the core logic pure, so the core is testable without mocks and the effects are visible in one place.

## 7. Boring technology

**PRIN-15** SHOULD choose well-understood technology for everything that does not differentiate the product. Each novel tool costs attention that is then unavailable for the product. Spend "innovation tokens" only where the product is different.

**PRIN-16** MUST record any decision that a later reader would otherwise re-derive (the choice, the alternatives, why) in the project's decision record, in the same change that makes it (see `10-documentation-and-decisions.md`).

## 8. Sources

- Beck's design rules, via Fowler (2015): https://martinfowler.com/bliki/BeckDesignRules.html
- YAGNI, Fowler (2015): https://martinfowler.com/bliki/Yagni.html
- The Wrong Abstraction, Metz (2016): https://sandimetz.com/blog/2016/1/20/the-wrong-abstraction
- AHA Programming, Dodds (2020): https://kentcdodds.com/blog/aha-programming
- DRY as knowledge, Hunt & Thomas, The Pragmatic Programmer 2nd ed. (2019), topic 9
- A Philosophy of Software Design vs Clean Code debate, Ousterhout & Martin (2024–25): https://github.com/johnousterhout/aposd-vs-clean-code
- CUPID, North (2022): https://dannorth.net/cupid-for-joyful-coding/
- Choose Boring Technology, McKinley (2015): https://mcfunley.com/choose-boring-technology
