import json
from pathlib import Path

import pytest

from ckm.config import Config, load_config
from ckm.parse import page_id_from_filename
from ckm.pilot import score_pilot
from ckm.redact import scan
from ckm.text import normalize_document, slugify


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Page-Title_123456.html", "123456"),
        ("8402883980.html", "8402883980"),
        ("index.html", None),
        ("Notes_v2.html", None),
    ],
)
def test_page_id_from_filename(name: str, expected: str | None) -> None:
    assert page_id_from_filename(name) == expected


def test_slugify_is_ascii_kebab_and_never_empty() -> None:
    assert slugify("Café — Month-End / Q1") == "cafe-month-end-q1"
    assert slugify("***") == "untitled"


def test_normalize_document_is_byte_stable() -> None:
    assert normalize_document("a  \r\n\r\n\r\n\nb\n\n") == "a\n\nb\n"


@pytest.mark.parametrize(
    ("text", "finding"),
    [
        ("key AKIAABCDEFGHIJKLMNOP", "aws_access_key"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
        ("ssn 123-45-6789", "us_ssn"),
        ("card 4111 1111 1111 1111", "card_number"),
    ],
)
def test_redaction_patterns(text: str, finding: str) -> None:
    assert [f.name for f in scan(text, Config())] == [finding]


def test_card_pattern_requires_luhn() -> None:
    assert scan("ref 4111 1111 1111 1112", Config()) == []


def test_config_rejects_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "ckm.json"
    path.write_text(json.dumps({"skip_clases": []}))
    with pytest.raises(ValueError, match="skip_clases"):
        load_config(path)


def test_pilot_scoring(tmp_path: Path) -> None:
    questions = tmp_path / "q.csv"
    answers = tmp_path / "a.csv"
    questions.write_text(
        "id,question,expected_page_ids,notes\n"
        "q1,When is sign-off?,100002,\n"
        "q2,Who owns payroll?,,not in the space\n"
        "q3,What is a variance?,100003,\n"
    )
    answers.write_text(
        "id,cited_page_ids,said_unknown,answer\n"
        "q1,100002;100001,no,Day 5\n"
        "q2,,yes,Not covered\n"
        "q3,100001,no,wrong page\n"
    )
    result = score_pilot(questions, answers)
    assert (result.cited_expected, result.answerable) == (1, 2)
    assert (result.correct_unknown, result.unanswerable) == (1, 1)
    assert result.misses == ["q3: expected one of ['100003']"]
