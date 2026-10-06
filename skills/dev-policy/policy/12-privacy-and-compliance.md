# 12 — Privacy, data handling and compliance

Applies when a change stores, moves, exports, logs, retains or deletes personal or customer data, or sends data to a third party (including an AI model). Written for an Australian B2B product that may hold government OFFICIAL data; adapt the regime names for other jurisdictions, not the rules.

Contents: 1 Classification · 2 Residency · 3 Collection and use · 4 Retention and deletion · 5 Breaches · 6 Third parties and AI · 7 Evidence for assessors · 8 Sources

## 1. Classification

**PRIV-01** MUST classify the data the product holds (for an Australian government customer: OFFICIAL or OFFICIAL: Sensitive) and record the classification where the code can enforce it. Anything above the designed classification is refused at the boundary, not handled "carefully".

**PRIV-02** MUST NOT design for PROTECTED unless the customer requires it: it brings certified hosting, assessed platforms, personnel clearances and approved cryptography that a lean build cannot meet. State the ceiling explicitly in the architecture document.

## 2. Residency

**PRIV-03** MUST keep data at rest, backups, logs and telemetry in the required jurisdiction (for Australia: Australia East, with Australia Southeast for recovery). Replication across borders is off.

**PRIV-04** MUST record any processing that leaves the jurisdiction (AI inference in a multi-region deployment, a US-hosted ticketing system) as an accepted risk with an owner, a legal basis, and the condition that reopens it. Identity services that are inherently global are stated as such.

## 3. Collection and use

**PRIV-05** MUST collect only what the feature needs (Australian Privacy Principle 3) and use it only for the purpose it was collected for (APP 6). A field added "because it might be useful" is a liability, not an asset.

**PRIV-06** MUST publish a privacy policy that matches what the product actually does (APP 1), and update it in the same change that changes the data flow.

**PRIV-07** MUST give users access to and correction of their personal information through a defined path (APP 12 and 13), even if that path is a manual procedure in the runbook at first.

## 4. Retention and deletion

**PRIV-08** MUST write a retention schedule per data category and implement it: personal information no longer needed is destroyed or de-identified (APP 11.2). "Keep everything forever" is a decision that must be recorded as one, with its reason (an audit obligation, for instance).

**PRIV-09** MUST make deletion real across copies: primary rows, derived rows, object storage, backups beyond their retention window, logs. A deleted vendor that still appears in an export is a breach.

**PRIV-10** MUST keep the audit trail's own retention separate and longer than the records it describes; the audit event of a deletion survives the deletion.

## 5. Breaches

**PRIV-11** MUST have a written procedure for the Notifiable Data Breaches scheme: how a suspected breach is assessed, who decides, the 30-day assessment window, and what is notified to the regulator and to affected individuals.

**PRIV-12** MUST treat a cross-tenant exposure, a secret leak or an unverified-recipient alert as a potential breach and run the procedure, not an informal judgement.

## 6. Third parties and AI

**PRIV-13** MUST assess any third party that receives personal or customer data (APP 8 for overseas recipients): what they receive, where it is processed, their retention, their contractual commitments (no training, no secondary use), and what residual risk the owner accepts.

**PRIV-14** MUST keep raw record content out of systems that are not in scope for the data's classification: a bug report to an offshore tracker carries a description, never the screenshot or the record.

**PRIV-15** MUST send only the minimum to an AI model, label the task and tenant in the audit record, and keep the content out of logs (`05-security.md`, SEC-47 and SEC-48).

## 7. Evidence for assessors

**PRIV-16** MUST keep the artefacts an assessor will ask for current and findable: the architecture description, the risk register, the decision record, the control mapping (ISM, Essential Eight or the applicable regime), the incident records, the tested backup restore, the retention schedule and the privacy policy.

**PRIV-17** MUST produce an application self-assessment against the applicable control catalogue (for Australia, the ISM, with ASVS as the web-application standard it names) before the first customer commitment, and keep it versioned with the code.

## 8. Sources

- Australian Privacy Principles quick reference, OAIC: https://www.oaic.gov.au/privacy/australian-privacy-principles/australian-privacy-principles-quick-reference
- APP 8 cross-border disclosure guidelines, OAIC (v1.3, Oct 2025): https://www.oaic.gov.au/privacy/australian-privacy-principles-guidelines/chapter-8-app-8-cross-border-disclosure-of-personal-information
- Notifiable Data Breaches scheme, OAIC: https://www.oaic.gov.au/privacy/notifiable-data-breaches
- Australian Government Information Security Manual (ISM), ACSC: https://www.cyber.gov.au/business-government/asds-cyber-security-frameworks/ism
- Essential Eight maturity model, ACSC: https://www.cyber.gov.au/business-government/asds-cyber-security-frameworks/essential-eight
- Hosting Certification Framework: https://www.hostingcertification.gov.au/
- OWASP Top 10 for LLM Applications (2025): https://genai.owasp.org/llm-top-10/
