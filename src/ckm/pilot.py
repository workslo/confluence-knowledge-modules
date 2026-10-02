"""Score a retrieval pilot: did the agent cite the right module, and say "unknown" when it should?

questions.csv  id, question, expected_page_ids (";"-separated, empty = should say unknown), notes
answers.csv    id, cited_page_ids (";"-separated), said_unknown (yes/no), answer

Record every miss as a content or taxonomy issue to fix in the vault, not as "the AI".
"""

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PilotResult:
    total: int
    cited_expected: int  # answerable questions where >=1 expected page was cited
    answerable: int
    correct_unknown: int  # unanswerable questions where the agent said unknown
    unanswerable: int
    misses: list[str]

    def summary(self) -> str:
        hit = self.cited_expected / self.answerable if self.answerable else 0.0
        unk = self.correct_unknown / self.unanswerable if self.unanswerable else 1.0
        return (
            f"questions={self.total} citation_hit_rate={hit:.0%} "
            f"({self.cited_expected}/{self.answerable}) "
            f"unknown_when_unknown={unk:.0%} ({self.correct_unknown}/{self.unanswerable})"
        )


def _ids(cell: str | None) -> set[str]:
    return {part.strip() for part in (cell or "").split(";") if part.strip()}


def score_pilot(questions_csv: Path, answers_csv: Path) -> PilotResult:
    with questions_csv.open(encoding="utf-8", newline="") as handle:
        questions = {row["id"]: row for row in csv.DictReader(handle)}
    with answers_csv.open(encoding="utf-8", newline="") as handle:
        answers = {row["id"]: row for row in csv.DictReader(handle)}

    cited = answerable = correct_unknown = unanswerable = 0
    misses: list[str] = []
    for qid, question in sorted(questions.items()):
        expected = _ids(question.get("expected_page_ids"))
        answer = answers.get(qid)
        if answer is None:
            misses.append(f"{qid}: no answer recorded")
            continue
        said_unknown = (answer.get("said_unknown") or "").strip().lower() in {"yes", "y", "true"}
        if expected:
            answerable += 1
            if expected & _ids(answer.get("cited_page_ids")):
                cited += 1
            else:
                misses.append(f"{qid}: expected one of {sorted(expected)}")
        else:
            unanswerable += 1
            if said_unknown:
                correct_unknown += 1
            else:
                misses.append(f"{qid}: should have said the evidence is missing")
    return PilotResult(len(questions), cited, answerable, correct_unknown, unanswerable, misses)
