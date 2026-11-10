#!/usr/bin/env python3
"""
json_to_csv.py -- validate an exam JSON file and convert it to quiz CSV.

Usage:
    python3 json_to_csv.py EXAM.json [OUTPUT.csv]

If no output path is given, the file is named from the exam title and
version, e.g. "python-basics_v1.0.csv".

The exam is checked before anything is written. Every problem found is
listed at once, so one run tells you everything to fix:

    error    the exam would grade incorrectly or fail to load;
             nothing is written
    warning  a default will be used; the file is still written

Output layout:
    # title: Python Basics            <- metadata lines, "# key: value"
    # version: 1.0
    ...
    id,type,subject,text,options,correct_answer,explanation
    1,multiple-choice,Geek History,"Who was ...","A=Jillian ...|B=Guido ...",B,"..."

Notes:
    * "options" is a "|"-separated list of "KEY=text" pairs, empty for
      short-answer questions.
    * Multi-line question text is fine -- csv quotes it automatically.
"""

import csv
import json
import sys

FIELDNAMES = ["id", "type", "subject", "text", "options", "correct_answer", "explanation"]
META_KEYS = ["title", "version", "author", "duration_minutes", "passing_score_percentage"]
CHOICE_TYPES = ("multiple-choice", "true-false")
VALID_TYPES = CHOICE_TYPES + ("short-answer",)
OPTION_SEP = "|"
KEY_SEP = "="


def slugify(text):
    """Lowercase, hyphenated, filename-safe version of text."""
    slug = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "exam"


def text_of(container, key):
    """Trimmed string for a key that may be missing, None, or a number."""
    value = container.get(key)
    return "" if value is None else str(value).strip()


# --------------------------------------------------------------- validation


def check_meta(meta, errors, warnings):
    for key in ("title", "version"):
        if not text_of(meta, key):
            warnings.append(f"exam_meta has no {key}; the quiz will show a placeholder")

    # These two decide the time limit and the pass mark. A bad value would
    # quietly fall back to "no limit" or 70%, changing how people are graded.
    for key, highest in (("duration_minutes", None), ("passing_score_percentage", 100)):
        if key not in meta or meta[key] is None:
            warnings.append(f"exam_meta has no {key}")
            continue
        try:
            value = float(meta[key])
        except (TypeError, ValueError):
            errors.append(f"exam_meta {key} must be a number, found {meta[key]!r}")
            continue
        if value < 0 or (highest is not None and value > highest):
            limit = f"between 0 and {highest}" if highest is not None else "0 or more"
            errors.append(f"exam_meta {key} must be {limit}, found {value:g}")


def check_options(raw, qtype, where, errors, warnings):
    """Validate one question's options. Returns the uppercased keys found."""
    keys = []
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        errors.append(f"{where}: options must be a list, found {type(raw).__name__}")
        return keys

    if qtype in CHOICE_TYPES and len(raw) < 2:
        errors.append(f"{where}: a {qtype} question needs at least two options, found {len(raw)}")
    elif qtype == "short-answer" and raw:
        warnings.append(f"{where}: short-answer questions ignore options")

    for index, option in enumerate(raw, start=1):
        if not isinstance(option, dict):
            errors.append(f"{where}: option {index} must be an object, found {type(option).__name__}")
            continue
        key = text_of(option, "key")
        value = text_of(option, "value")
        label = repr(key) if key else f"{index}"

        if not key:
            errors.append(f"{where}: option {index} has no key")
        elif key.upper() in keys:
            errors.append(f"{where}: option key {key!r} is used twice")
        else:
            keys.append(key.upper())

        if not value:
            errors.append(f"{where}: option {label} has no text")
        for char in (OPTION_SEP, KEY_SEP):
            if char in value:
                errors.append(
                    f"{where}: option {label} contains {char!r}, "
                    "which the CSV uses to separate options"
                )
    return keys


def check_answer(correct, qtype, keys, where, errors):
    """The check that matters most: an unanswerable question is silent."""
    if qtype in CHOICE_TYPES:
        if not correct:
            errors.append(f"{where}: no correct_answer")
        elif keys and correct.upper() not in keys:
            errors.append(
                f"{where}: correct_answer {correct!r} is not one of the option "
                f"keys ({', '.join(keys)}); nobody could answer this correctly"
            )
    elif qtype == "short-answer":
        if not correct:
            errors.append(f"{where}: no correct_answer; every answer would be marked wrong")
        elif any(not part.strip() for part in correct.split(OPTION_SEP)):
            errors.append(f"{where}: correct_answer {correct!r} has an empty alternative")


def validate(exam):
    """Return (errors, warnings). Nothing should be written if errors exist."""
    errors, warnings = [], []

    if not isinstance(exam, dict):
        return [f"the top level must be a JSON object, found {type(exam).__name__}"], warnings

    meta = exam.get("exam_meta")
    if meta is None:
        warnings.append("no exam_meta section; defaults will be used throughout")
        meta = {}
    elif not isinstance(meta, dict):
        errors.append(f"exam_meta must be an object, found {type(meta).__name__}")
        meta = {}
    check_meta(meta, errors, warnings)

    questions = exam.get("questions")
    if questions is None:
        errors.append("no questions section")
        questions = []
    elif not isinstance(questions, list):
        errors.append(f"questions must be a list, found {type(questions).__name__}")
        questions = []
    elif not questions:
        errors.append("the questions list is empty")

    seen_ids = {}
    for position, question in enumerate(questions, start=1):
        where = f"question {position}"
        if not isinstance(question, dict):
            errors.append(f"{where}: must be an object, found {type(question).__name__}")
            continue

        qid = text_of(question, "id")
        if qid:
            where = f"question {position} (id {qid})"
            if qid in seen_ids:
                errors.append(f"{where}: id already used by question {seen_ids[qid]}")
            else:
                seen_ids[qid] = position
        else:
            warnings.append(f"{where}: no id; the CSV row number will be used instead")

        if not text_of(question, "text"):
            errors.append(f"{where}: text is empty; the quiz would skip this question silently")
        if not text_of(question, "subject"):
            warnings.append(f"{where}: no subject; it will be grouped under 'General'")
        if not text_of(question, "explanation"):
            warnings.append(f"{where}: no explanation; nothing will be shown in the review")

        qtype = text_of(question, "type").lower()
        if not qtype:
            errors.append(f"{where}: no type; expected one of {', '.join(VALID_TYPES)}")
            continue
        if qtype not in VALID_TYPES:
            errors.append(f"{where}: unknown type {qtype!r}; expected one of {', '.join(VALID_TYPES)}")
            continue

        keys = check_options(question.get("options"), qtype, where, errors, warnings)
        check_answer(text_of(question, "correct_answer"), qtype, keys, where, errors)

    return errors, warnings


# --------------------------------------------------------------- conversion


def encode_options(options):
    """[{'key': 'A', 'value': 'x'}, ...] -> 'A=x|B=y'. Validated beforehand."""
    parts = []
    for option in options:
        key = text_of(option, "key")
        value = text_of(option, "value")
        if OPTION_SEP in value or KEY_SEP in value:
            raise ValueError(f"Option {key!r} contains a reserved character: {value!r}")
        parts.append(f"{key}{KEY_SEP}{value}")
    return OPTION_SEP.join(parts)


def convert(exam, csv_path=None):
    """Write the CSV. Call validate() first -- this assumes a clean exam."""
    meta = exam.get("exam_meta") or {}
    questions = exam.get("questions") or []

    if csv_path is None:
        title = meta.get("title", "exam")
        version = meta.get("version", "1.0")
        csv_path = f"{slugify(str(title))}_v{version}.csv"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        for key in META_KEYS:
            if key in meta:
                f.write(f"# {key}: {meta[key]}\n")
        for key, value in meta.items():          # anything not in META_KEYS
            if key not in META_KEYS:
                f.write(f"# {key}: {value}\n")

        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        for question in questions:
            writer.writerow({
                "id": question.get("id", ""),
                "type": question.get("type", ""),
                "subject": question.get("subject", ""),
                "text": question.get("text", ""),
                "options": encode_options(question.get("options") or []),
                "correct_answer": question.get("correct_answer", ""),
                "explanation": question.get("explanation", ""),
            })

    return csv_path


# --------------------------------------------------------------------- main


def main(argv):
    if not 2 <= len(argv) <= 3:
        print("Usage: python3 json_to_csv.py EXAM.json [OUTPUT.csv]", file=sys.stderr)
        return 1
    json_path = argv[1]

    try:
        with open(json_path, encoding="utf-8") as f:
            exam = json.load(f)
    except OSError as err:
        print(f"Could not read {json_path}: {err}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as err:
        print(f"{json_path} is not valid JSON: {err}", file=sys.stderr)
        return 1

    errors, warnings = validate(exam)

    for warning in warnings:
        print(f"warning: {warning}")
    if errors:
        count = len(errors)
        print(
            f"\n{json_path} has {count} problem{'s' if count > 1 else ''}; nothing was written:",
            file=sys.stderr,
        )
        for error in errors:
            print(f"  error: {error}", file=sys.stderr)
        return 1

    out = convert(exam, argv[2] if len(argv) == 3 else None)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
