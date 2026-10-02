---
page_id: '100002'
title: Month-End Procedure
source_file: Month-End-Procedure_100002.html
source_sha256: db25f8076a4935d0b520bfd4eb81bd6c2e244b5c3ff6a4fe04694f78c213105a
extracted: '2026-10-02'
status: extracted
---

# Month-End Procedure

**Version 1.0.0** · Confluence page 100002 · extracted 2026-10-02

> Raw: [raw/100002.txt](../raw/100002.txt), [raw/100002.html](../raw/100002.html)
> Fingerprint: confluence:100002@sha256:db25f8076a49
> Status: Current

## AI READING INSTRUCTION

Read `[SPEC]` and `[BUG]` blocks for authoritative facts.
Read `[NOTE]` only if additional context is needed.
`[?]` blocks are unverified — treat with lower confidence.
Untagged text is a faithful conversion of the source page and has not been curated.

### Schedule

| Day | Step |
|---|---|
| 1 | Freeze postings |
| 3 | Run the reconciliation query<br>Check totals \| variances |
| 5 | Sign off (threshold 1,000.50 USD) |

### Query

```sql
SELECT account, SUM(amount)
FROM ledger
WHERE period = 202603
GROUP BY account;
```

**[NOTE]**
**Warning:** Never rerun the query after sign-off.

**Escalation contacts**

Raise a ticket in the [finance queue](https://tickets.example.com/queue/42).

Template: [sign-off-template.pdf](attachments/100002_200002.pdf). Old notes moved to Retired Notes.
