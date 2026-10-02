# Roadmap — what v2 would add

1. **A real model behind `propose_next_steps`.** Today it is a deterministic
   template stub. The pipeline is already shaped for the swap: wording is
   proposed, decisions stay in code. v2 plugs a real backend in, keeps
   RISK_RULES, the router, and the approval gate untouched, and re-measures
   the cost model (the per-stage token recording makes this one command).
2. **A real injection classifier.** The pattern list in `detect_injection()`
   catches the rehearsal's attacks; production wants a trained layer plus
   human review of everything flagged.
3. **Retrieval that understands meaning.** Keyword overlap misses paraphrase
   ("fee waiver" vs. "refund"). Embeddings + a reranker, with the verbatim
   quote requirement kept.
4. **A real approval surface.** The JSON queue becomes a UI or chat approval
   with identity, signed audit entries, and expiry on stale requests.
5. **Real action backends.** The `actions.py` stubs become idempotent API
   calls (email, payments, account management) with dry-run support and
   per-action rollback notes.
6. **PII redaction before artifact write.** Quote the report for the audit
   trail, redact SSNs/card numbers in the shareable summary.
7. **Retrieval caching.** Identical exception types against an unchanged
   policy set skip re-retrieval (the cost model's cheapest lever after
   template length).
8. **Multi-case queue view.** One operator dashboard across cases instead of
   one queue file per run.
9. **Eval expansion.** Adversarial paraphrases of the injection cases, and
   policy-conflict cases (two policies disagreeing) routed to human review.

Deliberately out of scope: autonomous execution without approval. That is
the line the lab draws, and v2 keeps it.
