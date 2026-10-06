# 07 — Frontend

Applies when touching React pages, components, hooks, contexts, forms, routing, styling or anything a user sees. A project's own UI conventions (design tokens, component library, page patterns) are the Tier-2 overlay on top of this.

Contents: 1 Components · 2 State · 3 Data fetching · 4 Effects and hooks · 5 Forms and input · 6 Errors and empty states · 7 Accessibility · 8 Performance and responsiveness · 9 Security in the browser · 10 Sources

## 1. Components

**FE-01** SHOULD build with composition: pass `children` and elements before reaching for context or prop drilling. Small components composed, never inheritance.

**FE-02** MUST keep shared components stateless and presentational; data fetching, navigation and business decisions live in page components or hooks.

**FE-03** MUST keep one page component per route and keep every authenticated page inside the application layout, so navigation, title and session handling are never forgotten on a new page.

## 2. State

**FE-04** MUST separate server state (data that lives in the API) from client state (what is open, what is typed). Server state belongs in a fetching hook or query cache, never copied into local state or context.

**FE-05** SHOULD keep state as low in the tree as possible and lift it only to the nearest common parent. Derive values during render instead of storing them.

**FE-06** MUST represent mutually exclusive conditions as one status union (`'idle' | 'loading' | 'error' | 'success'`), never as several booleans that can contradict each other.

**FE-07** MUST use context only for cross-cutting, slowly changing values (session, theme, notifications). AVOID one large context that re-renders the whole tree on every change.

**FE-08** SHOULD use a reducer with a discriminated action union for complex nested state (an editor, a wizard), and keep tab and filter state in the URL so a reload and a shared link reproduce the view.

## 3. Data fetching

**FE-09** MUST render the three states of every fetched view explicitly: loading, error (with a retry), content. A page that shows an empty table while loading teaches users that the data is missing.

**FE-10** MUST route every API call through a typed service module generated from the contract, never a bare `fetch` or `axios` call in a component.

**FE-11** MUST re-read after a save: the UI reflects what the server stored, not what the client sent. Optimistic updates roll back on failure.

## 4. Effects and hooks

**FE-12** MUST follow the Rules of Hooks (top level only; enforced by `eslint-plugin-react-hooks` including `exhaustive-deps`).

**FE-13** AVOID `useEffect` for transforming data or reacting to user events. Effects synchronise with external systems; everything else is a derived value or an event handler.

**FE-14** SHOULD extract reusable stateful logic into custom hooks, which never import contexts; context-dependent behaviour belongs in the consumer.

## 5. Forms and input

**FE-15** MUST validate on the client for feedback and on the server for truth; the server's error messages are shown field by field, not as a generic toast.

**FE-16** MUST disable the submit control while a request is in flight and show the outcome inline. Double submission is a data bug, not a UX nit.

**FE-17** SHOULD auto-save long-running editors and tell the user when the last save happened.

## 6. Errors and empty states

**FE-18** MUST wrap the application in an error boundary and each route in a second one, so one broken page does not take down navigation.

**FE-19** MUST design empty states deliberately: what the user can do next, not a blank table.

**FE-20** MUST extract errors from the API envelope by code, never by matching message text.

## 7. Accessibility

**FE-21** MUST meet WCAG 2.1 AA: keyboard operability for every control, visible focus, labels on every input, `role` and `tabIndex` on any non-button that is clickable, sufficient contrast, no information carried by colour alone.

**FE-22** MUST give every page a document title and a single `h1`; dialogs trap focus and return it on close.

## 8. Performance and responsiveness

**FE-23** SHOULD lazy-load uncommon routes, paginate every list, and avoid rendering thousands of rows at once.

**FE-24** MUST work at phone width without horizontal scrolling for the flows a user on a phone would plausibly run (approvals, reading a questionnaire).

## 9. Security in the browser

**FE-25** MUST NOT use `dangerouslySetInnerHTML` without a sanitiser and a review comment. Never build HTML from strings.

**FE-26** MUST NOT store tokens in `localStorage`; the refresh credential is an `HttpOnly` cookie, the access token lives in memory.

**FE-27** MUST NOT trust the client for authorisation decisions; hiding a button is a convenience, the server check is the control.

## 10. Sources

- Choosing the state structure, React docs: https://react.dev/learn/choosing-the-state-structure
- You might not need an effect, React docs: https://react.dev/learn/you-might-not-need-an-effect
- Rules of Hooks, React docs: https://react.dev/reference/rules/rules-of-hooks
- React Query as a state manager, Dominik Dorfmeister (2021): https://tkdodo.eu/blog/react-query-as-a-state-manager
- Application state management with React, Dodds (2020): https://kentcdodds.com/blog/application-state-management-with-react
- WCAG 2.1: https://www.w3.org/TR/WCAG21/
- OWASP HTML5 and DOM-based XSS cheat sheets: https://cheatsheetseries.owasp.org/
