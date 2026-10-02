"""Lab 5 corpus + eval-question generator.

Deterministic: every draw comes from random.Random(SEED). 40 documents
(8 topics x 5 departments), each 3-6 paragraphs of 2-4 sentences with
concrete distinctive facts (numbers, thresholds, day counts). Also builds
data/eval_questions.json: 26 answerable questions generated FROM the corpus
(gold = {doc_id, answer_phrase}, a distinctive substring of one paragraph)
and 4 unanswerable questions whose vocabulary is absent from the corpus
(verified: max keyword overlap with any chunk <= 1).

Usage:
    PYTHONPATH=src:../lab-02/src .venv/bin/python -m lab05.generate
(or python src/lab05/generate.py)
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
LAB02_SRC = Path(__file__).resolve().parent.parent.parent.parent / "lab-02" / "src"
if str(LAB02_SRC) not in sys.path:
    sys.path.insert(0, str(LAB02_SRC))

from lab02.tools import keywords, score_passage  # noqa: E402

SEED = 42

DEPARTMENTS = ["HR", "Finance", "IT", "Operations", "Legal"]
DEPT_CODES = {"HR": "HR", "Finance": "FIN", "IT": "IT",
              "Operations": "OPS", "Legal": "LEG"}
TOPICS = [
    ("PTO", "PTO"),
    ("EXP", "expense"),
    ("DATA", "data retention"),
    ("INC", "incident response"),
    ("REM", "remote work"),
    ("PROC", "procurement"),
    ("ONB", "onboarding"),
    ("PWD", "password"),
]

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


# ------------------------------------------------------------------ slots
# Each topic: sentence templates + slot samplers. Slot values are concrete
# and distinctive (rates, caps, day counts, thresholds).

def _c(rng, opts):
    return rng.choice(opts)


TOPIC_SENTENCES: dict[str, list[str]] = {
    "PTO": [
        "Employees accrue {accrual} PTO days per month, up to an annual cap of {cap} days.",
        "Unused PTO up to {carry} days carries over into January; anything above that is forfeited.",
        "New hires begin accruing PTO after a {wait} day waiting period from their start date.",
        "PTO requests of {long} or more consecutive days require manager approval {notice} business days in advance.",
        "The blackout calendar blocks PTO during {blackout_weeks} peak weeks each {season}.",
        "Part-time staff working at least {hours} hours per week accrue PTO at {rate_pct} percent of the full-time rate.",
        "Employees with {tenure} or more years of tenure earn an extra {bonus} PTO day per year.",
        "PTO payouts on departure are capped at {payout} days and paid at the final hourly rate.",
        "Sick leave is separate from PTO: {sick} paid sick days per year, usable in {increment} hour increments.",
        "Managers must respond to PTO requests within {resp} business days or the request auto-approves.",
        "Floating holidays number {float} per year and expire on {expiry} if unused.",
        "Parental leave runs {parental} weeks at {pay_pct} percent pay, in addition to accrued PTO.",
        "PTO balances are tracked in the {sig} leave system.",
    ],
    "EXP": [
        "The meal per diem is capped at ${meal} per day for domestic travel.",
        "The hotel nightly limit is ${hotel} in major metros and ${hotel2} elsewhere.",
        "Expenses above ${threshold} require pre-approval from a director.",
        "Receipts are required for every expense over ${receipt}.",
        "Mileage is reimbursed at ${mile} per mile using the standard route distance.",
        "Expense reports must be filed within {days} days of travel completion.",
        "Client entertainment over ${ent} per person needs VP sign-off.",
        "Corporate card limits default to ${card} per cycle for individual contributors.",
        "Currency conversion uses the {bank} rate on the transaction date plus a {fee} percent fee.",
        "Duplicate submissions are flagged after {dup} identical receipts in a quarter.",
        "The home office stipend is ${stipend} per year for remote staff.",
        "Airfare must be booked at least {book} days ahead; business class requires flights of {hours} or more hours.",
        "Expense policy clarifications are published in the {sig} bulletin.",
    ],
    "DATA": [
        "Customer transaction logs are retained for {years} years, then anonymized.",
        "Email archives persist for {email} months before automatic deletion.",
        "Backups follow a {backup} rotation with offsite copies in {sites} regions.",
        "Access logs are stored for {access} days for security review.",
        "Financial records follow a {fin} year retention to satisfy audit rules.",
        "Support tickets are purged {ticket} days after resolution.",
        "Deleted user accounts are held in cold storage for {cold} days before erasure.",
        "Legal holds suspend all deletion for affected custodians until the hold is released.",
        "Analytics aggregates older than {agg} months are rolled up and the raw events dropped.",
        "Encryption keys rotate every {key} days; retired keys are archived for {keyarch} year.",
        "Data subject deletion requests must be honored within {dsr} days.",
        "Marketing consent records are kept for {consent} years after opt-out.",
        "The master retention schedule is maintained in the {sig} system.",
    ],
    "INC": [
        "Severity 1 incidents page the on-call engineer within {page} minutes.",
        "A bridge call must start within {bridge} minutes of a Sev1 declaration.",
        "Status updates go out every {update} minutes until the incident is resolved.",
        "Postmortems are due within {pm} business days of incident closure.",
        "Customer-facing outages trigger executive notification after {exec} minutes.",
        "Rollback decisions for Sev1 require {approvers} approver on the bridge.",
        "Incident commanders are drawn from a rotation of {ic} trained staff.",
        "War-room notes are archived in the incident record within {notes} hour of resolution.",
        "Repeat incidents with the same root cause within {repeat} days escalate to Sev1 automatically.",
        "On-call shifts are {shift} hours with a {handover} minute handover overlap.",
        "The blameless postmortem template v{pmv} is mandatory for Sev1 and Sev2.",
        "Detection SLA: alerts must fire within {detect} seconds of a threshold breach.",
        "Incident runbooks are stored in the {sig} wiki.",
    ],
    "REM": [
        "Remote staff must be online during {core1} to {core2} core hours in their timezone.",
        "The home internet stipend is ${net} per month with receipts.",
        "The equipment refresh cycle is {refresh} months for laptops.",
        "VPN must be connected for all internal tools; split tunneling is {split}.",
        "Video-on is expected for meetings with fewer than {video} participants.",
        "Remote employees may work from {countries} approved countries up to {abroad} days per year.",
        "Ergonomic assessments are offered every {ergo} months.",
        "Timezone spread on a team may not exceed {tz} hours without director approval.",
        "Coworking memberships up to ${cowork} per month are reimbursable.",
        "Async-first rule: decisions need a {async} hour comment window before closing.",
        "New remote hires get a {buddy} week buddy pairing.",
        "Office visits are reimbursed up to {visits} trips per quarter.",
        "Remote work norms are documented in the {sig} handbook.",
    ],
    "PROC": [
        "Purchases over ${po} require a purchase order before ordering.",
        "Vendor onboarding takes {onboard} business days including security review.",
        "Contracts above ${contract} need legal review and {sigs} signatures.",
        "Preferred vendors receive {pref} percent of category spend where available.",
        "Sole-source justifications are required above ${sole}.",
        "Invoice payment terms default to Net {net}.",
        "RFPs are mandatory for engagements over ${rfp}.",
        "Procurement cards cap at ${pcard} per transaction.",
        "Vendor performance reviews happen every {rev} months.",
        "Emergency purchases up to ${emerg} may bypass the PO with next-day filing.",
        "Software renewals need {renew} day advance notice to procurement.",
        "Conflict-of-interest disclosures are filed {coi} annually.",
        "Procurement exceptions are logged in the {sig} ledger.",
    ],
    "ONB": [
        "New hire paperwork must be completed {paper} days before day one.",
        "IT provisions accounts within {prov} hours of the signed offer.",
        "Orientation runs {orient} days covering culture, tools, and compliance.",
        "Every new hire is assigned a buddy for the first {buddyw} weeks.",
        "The {day30} day plan is reviewed with the manager at the midpoint check-in.",
        "Background checks complete within {bg} business days on average.",
        "Role-specific training paths contain {modules} modules due by day {dueday}.",
        "Managers schedule {oneonone} one-on-ones in the first month.",
        "The probation review happens at {prob} days with written feedback.",
        "Equipment ships {ship} days before the start date for remote hires.",
        "Compliance courses ({courses} total) must finish in the first {compdays} days.",
        "Team introductions are calendared across the first {introdays} days.",
        "Onboarding progress is tracked in the {sig} portal.",
    ],
    "PWD": [
        "Passwords must be at least {length} characters long.",
        "Passphrases of {words} or more words may skip complexity rules.",
        "Password rotation is every {rotate} days for privileged accounts.",
        "MFA is required for all {mfa} access, with no exceptions.",
        "Failed logins lock the account for {lock} minutes after {attempts} attempts.",
        "Password managers are {pm} for all staff; vaults are provisioned on day one.",
        "Service account secrets rotate every {secret} days via the vault.",
        "Shared credentials are {shared}; use named accounts with delegated access instead.",
        "Session timeout is {session} minutes of inactivity.",
        "Password reset links expire after {reset} minutes.",
        "Biometric unlock is {bio} on managed devices.",
        "Admin consoles require hardware keys; SMS codes are {sms}.",
        "Password guidance lives in the {sig} guide.",
    ],
}

TOPIC_SLOTS: dict[str, dict[str, list]] = {
    "PTO": {
        "sig": ['Zephyr', 'Yonder', 'Xanadu', 'Quill', 'Vantage', 'Wexford'],
        "accrual": ["1.0", "1.25", "1.5", "1.67", "2.0", "2.5"],
        "cap": [15, 18, 20, 22, 24, 25, 30], "carry": [5, 7, 10],
        "wait": [30, 60, 90], "long": [5, 7, 10], "notice": [10, 14, 21],
        "blackout_weeks": [2, 3, 4], "season": ["summer", "winter", "holiday", "year-end"],
        "hours": [20, 24, 30], "rate_pct": [50, 60, 75], "tenure": [3, 5, 7],
        "bonus": [1, 2, 3], "payout": [5, 10, 15], "sick": [5, 7, 10],
        "increment": [1, 2, 4], "resp": [2, 3, 5], "float": [1, 2, 3],
        "expiry": ["December 31", "January 31", "March 31"],
        "parental": [6, 8, 12], "pay_pct": [60, 80, 100],
    },
    "EXP": {
        "sig": ['Tally', 'Abacus', 'Tender', 'Voucher', 'Docket', 'Chit'],
        "meal": [45, 55, 65, 75], "hotel": [180, 220, 250, 300],
        "hotel2": [120, 140, 150], "threshold": [500, 1000, 1500, 2500],
        "receipt": [25, 50, 75], "mile": ["0.67", "0.70", "0.72"],
        "days": [14, 30, 45, 60], "ent": [75, 100, 150],
        "card": [2500, 5000, 7500], "bank": ["First National", "the corporate bank"],
        "fee": ["1.5", "2.0", "2.5"], "dup": [2, 3], "stipend": [500, 750, 1000],
        "book": [7, 14, 21], "hours": [6, 8],
    },
    "DATA": {
        "sig": ['Atlas', 'Beacon', 'Compass', 'Drift', 'Ember', 'Flint'],
        "years": [3, 5, 7], "email": [12, 18, 24],
        "backup": ["3-2-1", "grandfather-father-son"], "sites": [2, 3],
        "access": [90, 180, 365], "fin": [7, 10], "ticket": [30, 60, 90],
        "cold": [30, 60, 90], "agg": [13, 18, 24], "key": [30, 60, 90],
        "keyarch": [1, 2], "dsr": [15, 30, 45], "consent": [2, 3, 5],
    },
    "INC": {
        "sig": ['Siren', 'Pyre', 'Vigil', 'Halcyon', 'Kestrel', 'Ozone'],
        "page": [5, 10, 15], "bridge": [15, 30], "update": [15, 30],
        "pm": [3, 5], "exec": [30, 60], "approvers": ["1", "2"],
        "ic": [8, 12, 16], "notes": [1, 2], "repeat": [14, 30],
        "shift": [8, 12], "handover": [15, 30], "pmv": ["2.1", "3.0"],
        "detect": [30, 60, 120],
    },
    "REM": {
        "sig": ['Northstar', 'Harbor', 'Summit', 'Pioneer', 'Ridgeline', 'Tidewater'],
        "core1": ["9:00", "9:30", "10:00"], "core2": ["15:00", "16:00"],
        "net": [50, 75, 100], "refresh": [24, 36],
        "split": ["disabled", "prohibited", "blocked for sensitive subnets"],
        "video": [8, 10, 12], "countries": [5, 8, 12], "abroad": [30, 60, 90],
        "ergo": [6, 12], "tz": [8, 10], "cowork": [200, 300, 400],
        "async": [24, 48], "buddy": [2, 4], "visits": [2, 4],
    },
    "PROC": {
        "sig": ['Ironclad', 'Keystone', 'Lodestar', 'Meridian', 'Northgate', 'Overlook'],
        "po": [1000, 2500, 5000], "onboard": [5, 10, 15],
        "contract": [25000, 50000, 100000], "sigs": [2, 3],
        "pref": [70, 80, 90], "sole": [10000, 25000], "net": [30, 45, 60],
        "rfp": [50000, 100000], "pcard": [1000, 2500], "rev": [6, 12],
        "emerg": [1000, 2500, 5000], "renew": [30, 60, 90],
        "coi": ["once", "twice"],
    },
    "ONB": {
        "sig": ['Gateway', 'Launchpad', 'Onramp', 'Prelude', 'Springboard', 'Threshold'],
        "paper": [3, 5, 7], "prov": [24, 48, 72], "orient": [2, 3, 5],
        "buddyw": [2, 4, 6], "day30": [30, 60, 90], "bg": [3, 5, 10],
        "modules": [4, 6, 8], "dueday": [30, 45, 60], "oneonone": [2, 3, 4],
        "prob": [60, 90], "ship": [3, 5], "courses": [3, 4, 5],
        "compdays": [7, 14], "introdays": [5, 10],
    },
    "PWD": {
        "sig": ['Sentinel', 'Watchtower', 'Bulwark', 'Parapet', 'Rampart', 'Citadel'],
        "length": [12, 14, 16], "words": [4, 5], "rotate": [60, 90, 180],
        "mfa": ["remote", "all external", "privileged"], "lock": [15, 30],
        "attempts": [3, 5], "pm": ["mandatory", "required", "strongly encouraged"],
        "secret": [30, 90], "shared": ["prohibited", "banned", "forbidden"],
        "session": [10, 15, 30], "reset": [15, 30, 60],
        "bio": ["allowed", "encouraged", "supported"],
        "sms": ["deprecated", "not permitted", "disabled"],
    },
}


# ------------------------------------------------------------ generation

def _effective_date(rng: random.Random) -> str:
    year = rng.choice([2024, 2025, 2026])
    month = rng.randint(1, 6 if year == 2026 else 12)
    return f"{year}-{month:02d}"


def generate_corpus(seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    docs: list[dict] = []
    for ti, (tcode, tlabel) in enumerate(TOPICS):
        # signature values are dealt WITHOUT replacement: each doc in the
        # topic gets a lexically unique signature token (df == 1), which is
        # what makes same-topic documents distinguishable to the retriever.
        sig_vals = rng.sample(TOPIC_SLOTS[tcode]["sig"], len(DEPARTMENTS))
        for di, dept in enumerate(DEPARTMENTS):
            doc_id = f"{DEPT_CODES[dept]}-{tcode}-{ti + 1:02d}"
            sentences = TOPIC_SENTENCES[tcode][:]
            rng.shuffle(sentences)
            slots = TOPIC_SLOTS[tcode]

            def fill(s: str) -> str:
                vals = {k: _c(rng, v) for k, v in slots.items()
                        if k != "sig"}
                vals["sig"] = sig_vals[di]
                return s.format(**vals)

            filled = [fill(s) for s in sentences]
            # group into paragraphs of 3-5 sentences (3-5 paragraphs total);
            # longer paragraphs exceed 60 words so the chunk_size=60
            # experiment setting actually splits them (< 120 keeps the
            # default config at ~1 chunk per paragraph)
            paragraphs: list[str] = []
            i = 0
            while i < len(filled):
                remaining = len(filled) - i
                size = remaining if remaining <= 5 else rng.choice([3, 4, 5])
                paragraphs.append(" ".join(filled[i:i + size]))
                i += size
            docs.append({
                "doc_id": doc_id,
                "department": dept,
                "version": f"v{rng.randint(1, 3)}.{rng.randint(0, 9)}",
                "effective_date": _effective_date(rng),
                "title": f"{dept} {tlabel} policy",
                "paragraphs": paragraphs,
            })
    return docs


# ----------------------------------------------------- question building

def _doc_frequency(paragraphs: list[str]) -> dict[str, int]:
    df: dict[str, int] = {}
    for p in paragraphs:
        for tok in set(keywords(p)):
            df[tok] = df.get(tok, 0) + 1
    return df


def _distinctive_tokens(paragraph: str, df: dict[str, int], n: int) -> list[str]:
    toks = keywords(paragraph)
    toks.sort(key=lambda t: (df.get(t, 0), t))
    return toks[:n]


def _question_text(doc: dict, tlabel: str, kws: list[str]) -> str:
    return (f"What does the {doc['department']} {tlabel} policy "
            f"state about {', '.join(kws)}?")


def build_questions(corpus: list[dict]) -> list[dict]:
    from lab05.chunk import chunk_paragraphs
    from lab05.retrieve import Chunk, Retriever

    paras: list[tuple[str, str, str, str]] = []  # doc_id, dept, topic, text
    for d in corpus:
        tlabel = dict(TOPICS)[d["doc_id"].split("-")[1]]
        for p in d["paragraphs"]:
            paras.append((d["doc_id"], d["department"], tlabel, p))
    all_texts = [p[3] for p in paras]
    df = _doc_frequency(all_texts)

    chunks = [Chunk.from_dict(d) for d in chunk_paragraphs(corpus)]
    retr = Retriever(chunks)

    def selftest(question: str, phrase: str) -> bool:
        """Gold chunk (the one containing answer_phrase) must rank top-3
        under the default pipeline, else the question is not fair game."""
        hits = retr.retrieve(question, k=3, rerank=True)
        return any(phrase in c.text for c, _ in hits)

    # One candidate per doc: the paragraph holding the doc's signature
    # sentence. Its signature token has df == 1, so the question is
    # lexically discriminative against the other docs on the same topic.
    # Corpus is topic-major (8 topics x 5 depts); round-robin for spread.
    n_topics, n_depts = len(TOPICS), len(DEPARTMENTS)
    order = [ti * n_depts + di for di in range(n_depts)
             for ti in range(n_topics)]
    accepted: list[tuple[str, str, str]] = []  # question, doc_id, phrase
    for di in order:
        if len(accepted) >= 26:
            break
        doc = corpus[di]
        tcode = doc["doc_id"].split("-")[1]
        tlabel = dict(TOPICS)[tcode]
        sig_tok = next(v.lower() for v in TOPIC_SLOTS[tcode]["sig"]
                       if v.lower() in keywords(" ".join(doc["paragraphs"])))
        assert df.get(sig_tok, 0) == 1, f"signature token {sig_tok} not unique"
        p = next(p for p in doc["paragraphs"] if sig_tok in keywords(p))
        phrase = _answer_phrase(p, df, all_texts)
        if not phrase:
            continue
        others = [t for t in _distinctive_tokens(p, df, 6) if t != sig_tok]
        kws = [sig_tok] + others[:4]
        question = _question_text(doc, tlabel, kws)
        if selftest(question, phrase):
            accepted.append((question, doc["doc_id"], phrase))
    assert len(accepted) == 26, f"built {len(accepted)} answerable questions"

    questions: list[dict] = []
    for i, (question, doc_id, phrase) in enumerate(accepted, start=1):
        questions.append({
            "qid": f"q{i:02d}",
            "question": question,
            "answerable": True,
            "gold": {"doc_id": doc_id, "answer_phrase": phrase},
        })

    for q in _UNANSWERABLE:
        i += 1
        questions.append({
            "qid": f"q{i:02d}",
            "question": q,
            "answerable": False,
            "gold": None,
        })
    return questions


def _answer_phrase(paragraph: str, df: dict[str, int],
                   all_texts: list[str]) -> str | None:
    """Pick a short word window from the paragraph (inside the first 55
    words, so chunk 0 always covers it under every chunk-size/overlap
    setting) that is unique across the whole corpus. Uniqueness is what
    makes it a robust gold: the cited chunk contains it iff the gold
    paragraph was retrieved."""
    words = paragraph.split()[:55]
    cands: list[tuple[int, int, str]] = []
    for wlen in (5, 6, 7, 8):
        for s in range(0, len(words) - wlen + 1):
            phrase = " ".join(words[s:s + wlen])
            if sum(t.count(phrase) for t in all_texts) == 1:
                key = sum(df.get(t, 0) for t in keywords(phrase))
                cands.append((key, wlen, phrase))
    if not cands:
        return None
    cands.sort()
    return cands[0][2]


_UNANSWERABLE = [
    "What are the safety protocols for the lunar manufacturing plant?",
    "How often is the company yacht serviced for hull maintenance?",
    "What is the CEO's favorite restaurant for client dinners?",
    "What is the annual budget for the pet astronaut program?",
]


def verify_unanswerable(corpus: list[dict], questions: list[dict]) -> None:
    """Every unanswerable question must have max keyword overlap <= 1
    with any default-chunk of the corpus (same scoring the agent uses)."""
    from lab05.chunk import chunk_paragraphs
    chunks = chunk_paragraphs(corpus)
    for q in questions:
        if q["answerable"]:
            continue
        keys = keywords(q["question"])
        worst = max(score_passage(keys, c["text"]) for c in chunks)
        assert worst <= 1, (
            f"unanswerable {q['qid']} has keyword overlap {worst} > 1: "
            f"{q['question']!r}")


# ------------------------------------------------------------------ main

def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    corpus = generate_corpus(SEED)
    assert len(corpus) == 40
    _dump(DATA_DIR / "corpus.json", corpus)
    questions = build_questions(corpus)
    verify_unanswerable(corpus, questions)
    _dump(DATA_DIR / "eval_questions.json", questions)
    print(f"wrote {DATA_DIR / 'corpus.json'} "
          f"({len(corpus)} docs)")
    print(f"wrote {DATA_DIR / 'eval_questions.json'} "
          f"({len(questions)} questions)")


if __name__ == "__main__":
    main()
