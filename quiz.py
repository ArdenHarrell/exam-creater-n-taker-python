#!/usr/bin/env python3
"""
quiz.py -- a CSV-driven quiz runner. Standard library only, and only five
modules of it: csv, queue, sys, threading, time.

Usage:
    python3 quiz.py EXAM.csv [RESULTS.csv]

    EXAM.csv     the questions (see json_to_csv.py to generate one)
    RESULTS.csv  where attempts are logged; defaults to quiz_results.csv

Exam file format:
    Leading lines starting with "#" hold metadata as "# key: value".
    Recognised keys: title, version, author, duration_minutes,
    passing_score_percentage. Everything else is carried along but unused.

    Then a normal CSV with the header:
        id,type,subject,text,options,correct_answer,explanation

    type            multiple-choice | true-false | short-answer
    options         "|"-separated "KEY=text" pairs; empty for short-answer
    correct_answer  the option key, or for short-answer one or more
                    accepted answers separated by "|"

    Omit duration_minutes (or set it to 0) to run with no time limit.

The clock is hard: when duration_minutes runs out the quiz ends at once,
even mid-question. A half-typed answer does not count.

Results are appended to the log, one row per attempt, with the completion
date, a unique run id, and the exam name and version number.
"""

import csv
import queue
import sys
import threading
import time

# ---------------------------------------------------------------- constants

QUESTION_FIELDS = ["id", "type", "subject", "text", "options", "correct_answer", "explanation"]
OPTION_SEP = "|"
KEY_SEP = "="
COMMENT_PREFIX = "#"

DEFAULT_LOG = "quiz_results.csv"
DEFAULT_PASSING = 70.0

LOG_FIELDS = [
    "run_id",
    "date_completed",
    "exam_title",
    "version",
    "candidate",
    "questions",
    "answered",
    "correct",
    "percentage",
    "passing_score",
    "result",
    "completion",
    "seconds_used",
    "subject_breakdown",
]

# ------------------------------------------------------------------ helpers


def slugify(text):
    """Lowercase, hyphenated, filename-safe version of text."""
    slug = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "exam"


def normalize(text):
    """Loose comparison form for short answers: 'Print()' -> 'print'."""
    return text.strip().strip("()").casefold()


def clock(seconds):
    """4.0 -> '4:00'. Never shows a negative time."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def to_number(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def rule(char="-", width=64):
    return char * width


# ------------------------------------------------------- timed keyboard input


class Stop(Exception):
    """The quiz should end now. Subclasses say why."""


class TimedOut(Stop):
    """The deadline passed."""


class Quit(Stop):
    """The candidate asked to stop, or stdin closed."""


class Reader:
    """
    Keyboard input the main thread can give up on.

    input() blocks forever, so a daemon thread does the blocking read and
    hands completed lines over on a queue. The main thread waits only until
    the deadline. Anything typed after that sits unread in the queue, and
    because the thread is a daemon it never holds up interpreter exit.

    A thread is used rather than select() because select() cannot watch
    stdin on Windows -- only sockets.
    """

    def __init__(self):
        self.deadline = None            # a time.monotonic() value, or None
        self._lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            line = sys.stdin.readline()
            if not line:                # EOF
                self._lines.put(None)
                return
            self._lines.put(line.rstrip("\n"))

    def start_clock(self, seconds):
        """Begin a countdown of `seconds`. Pass 0 or None for no limit."""
        self.deadline = time.monotonic() + seconds if seconds else None

    def remaining(self):
        """Seconds left (None if untimed). Raises TimedOut if none are."""
        if self.deadline is None:
            return None
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimedOut
        return left

    def ask(self, prompt):
        """Show prompt and return the typed line. Raises TimedOut or Quit."""
        timeout = self.remaining()
        print(prompt, end="", flush=True)
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise TimedOut from None
        except KeyboardInterrupt:
            print()
            raise Quit from None
        if line is None:                # stdin closed
            print()
            raise Quit
        return line


# ------------------------------------------------------------------ loading


def parse_options(field):
    """'A=x|B=y' -> [('A', 'x'), ('B', 'y')]."""
    options = []
    for chunk in field.split(OPTION_SEP):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition(KEY_SEP)
        if not sep:
            raise ValueError(f"Malformed option {chunk!r}: expected KEY{KEY_SEP}text")
        options.append((key.strip().upper(), value.strip()))
    return options


def load_exam(path):
    """Return (meta, questions). Raises ValueError on a malformed file."""
    meta = {}
    body = []
    with open(path, newline="", encoding="utf-8") as f:
        in_body = False
        for line in f:
            if not in_body and line.lstrip().startswith(COMMENT_PREFIX):
                key, _, value = line.lstrip().lstrip(COMMENT_PREFIX).partition(":")
                if key.strip():
                    meta[key.strip().lower()] = value.strip()
                continue
            in_body = True          # metadata only counts before the header
            body.append(line)

    reader = csv.DictReader(body)
    missing = [c for c in QUESTION_FIELDS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"{path}: missing column(s): {', '.join(missing)}")

    questions = []
    for lineno, row in enumerate(reader, start=2):
        if not (row.get("text") or "").strip():
            continue                # skip blank padding rows
        qtype = (row["type"] or "").strip().lower()
        if qtype not in {"multiple-choice", "true-false", "short-answer"}:
            raise ValueError(f"{path} row {lineno}: unknown type {qtype!r}")
        question = {
            "id": (row["id"] or str(lineno)).strip(),
            "type": qtype,
            "subject": (row["subject"] or "General").strip(),
            "text": row["text"].strip(),
            "options": parse_options(row["options"] or ""),
            "correct_answer": (row["correct_answer"] or "").strip(),
            "explanation": (row["explanation"] or "").strip(),
        }
        if qtype != "short-answer" and not question["options"]:
            raise ValueError(f"{path} row {lineno}: {qtype} question has no options")
        questions.append(question)

    if not questions:
        raise ValueError(f"{path}: no questions found")
    return meta, questions


# ------------------------------------------------------------------ marking


def accepted_answers(question):
    """Short answers may list alternatives: 'input|input()'."""
    return [a for a in question["correct_answer"].split(OPTION_SEP) if a.strip()]


def interpret(question, raw):
    """Canonicalise user input, or return None if it isn't a usable answer."""
    answer = raw.strip()
    if not answer:
        return None
    if question["type"] == "short-answer":
        return answer
    upper = answer.upper()
    if upper in [k for k, _ in question["options"]]:
        return upper
    for key, value in question["options"]:      # allow typing "True", "False"
        if upper == value.strip().upper():
            return key
    return None


def is_correct(question, answer):
    if answer is None:
        return False
    if question["type"] == "short-answer":
        return any(normalize(answer) == normalize(a) for a in accepted_answers(question))
    return answer.upper() == question["correct_answer"].strip().upper()


# -------------------------------------------------------------------- asking


def show_question(question, position, total, remaining):
    header = f"Question {position} of {total}  [{question['subject']}]"
    if remaining is not None:
        header += f"  time left {clock(remaining)}"
    print()
    print(rule())
    print(header)
    print(rule())
    print(question["text"])
    if question["options"]:
        print()
        for key, value in question["options"]:
            print(f"  {key}) {value}")
    print()


def prompt_for(question, reader):
    """Ask until the input is usable. Returns the answer, or None to skip."""
    if question["type"] == "short-answer":
        hint = "Your answer"
    else:
        hint = "Your answer (" + "/".join(k for k, _ in question["options"]) + ")"

    while True:
        raw = reader.ask(f"{hint}, or 'skip' / 'quit': ")
        command = raw.strip().lower()
        if command == "quit":
            raise Quit
        if command == "skip":
            return None
        answer = interpret(question, raw)
        if answer is not None:
            return answer
        print("  Sorry, I didn't recognise that. Try again.")


# ------------------------------------------------------------------ running


def run_exam(questions, reader, duration_seconds):
    """
    Ask every question. Returns (records, seconds_used, completion) where
    completion is 'finished', 'timed_out' or 'quit'.
    """
    reader.start_clock(duration_seconds)
    started = time.monotonic()

    records = []
    completion = "finished"

    for position, question in enumerate(questions, start=1):
        try:
            show_question(question, position, len(questions), reader.remaining())
            answer = prompt_for(question, reader)
        except TimedOut:
            print("\n\nTime is up -- pencils down. This answer does not count.")
            completion = "timed_out"
            break
        except Quit:
            print("\nEnding the quiz early.")
            completion = "quit"
            break
        records.append({
            "question": question,
            "answer": answer,
            "correct": is_correct(question, answer),
        })

    for question in questions[len(records):]:       # never reached
        records.append({"question": question, "answer": None, "correct": False})

    return records, time.monotonic() - started, completion


# ------------------------------------------------------------------ scoring


def subject_breakdown(records):
    """'Output 1/1; Geek History 0/1' -- one entry per subject, in order."""
    order = []
    tally = {}
    for record in records:
        subject = record["question"]["subject"]
        if subject not in tally:
            tally[subject] = [0, 0]
            order.append(subject)
        tally[subject][1] += 1
        if record["correct"]:
            tally[subject][0] += 1
    return "; ".join(f"{s} {tally[s][0]}/{tally[s][1]}" for s in order)


def describe(question, answer):
    """'B' -> 'B (Guido van Rossum ...)' so a bare key means something."""
    answer = answer.strip()
    for key, value in question["options"]:
        if key == answer.upper():
            return f"{answer} ({value})"
    return answer


def describe_correct(question):
    """The expected answer, with short-answer alternatives spelled out."""
    if question["type"] == "short-answer":
        return " or ".join(a.strip() for a in accepted_answers(question))
    return describe(question, question["correct_answer"])


def report(records, meta, seconds_used, passing, completion):
    total = len(records)
    correct = sum(1 for r in records if r["correct"])
    answered = sum(1 for r in records if r["answer"] is not None)
    percentage = round(100.0 * correct / total, 1) if total else 0.0

    print()
    print(rule("="))
    print("REVIEW")
    print(rule("="))
    for record in records:
        question = record["question"]
        mark = "correct" if record["correct"] else "wrong"
        print(f"\nQ{question['id']} [{question['subject']}] -- {mark}")
        lines = question["text"].splitlines()
        for line in lines:                              # keeps code blocks intact
            print(f"  {line}" if line.strip() else "")
        if len(lines) > 1:              # keep a code block off the answer line
            print()
        given = describe(question, record["answer"]) if record["answer"] is not None else "(no answer)"
        print(f"  you said: {given}")
        if not record["correct"]:
            print(f"  answer:   {describe_correct(question)}")
            if question["explanation"]:
                print(f"  why:      {question['explanation']}")

    note = {"timed_out": "  (ran out of time)", "quit": "  (ended early)"}.get(completion, "")

    print()
    print(rule("="))
    print(f"{meta.get('title', 'Quiz')} v{meta.get('version', '?')}")
    print(f"Score:     {correct}/{total} ({percentage}%)   answered {answered}/{total}")
    print(f"Needed:    {passing}%")
    print(f"Time used: {clock(seconds_used)}{note}")
    print(f"Result:    {'PASS' if percentage >= passing else 'FAIL'}")
    print(rule("="))

    return {
        "questions": total,
        "answered": answered,
        "correct": correct,
        "percentage": percentage,
        "result": "PASS" if percentage >= passing else "FAIL",
        "completion": completion,
        "subject_breakdown": subject_breakdown(records),
    }


# ------------------------------------------------------------------ logging


def log_attempt(log_path, meta, candidate, summary, seconds_used):
    title = meta.get("title", "quiz")
    version = meta.get("version", "0")
    now = time.localtime()          # one reading, so id and date always agree
    run_id = f"{slugify(title)}-v{version}-{time.strftime('%Y%m%d-%H%M%S', now)}"

    row = {
        "run_id": run_id,
        "date_completed": time.strftime("%Y-%m-%d %H:%M:%S", now),
        "exam_title": title,
        "version": version,
        "candidate": candidate,
        "questions": summary["questions"],
        "answered": summary["answered"],
        "correct": summary["correct"],
        "percentage": summary["percentage"],
        "passing_score": to_number(meta.get("passing_score_percentage"), DEFAULT_PASSING),
        "result": summary["result"],
        "completion": summary["completion"],
        "seconds_used": round(seconds_used, 1),
        "subject_breakdown": summary["subject_breakdown"],
    }

    # "a+" appends and lets us read the file back: size 0 means write a
    # header, and existing run ids let us guarantee this one is unique.
    with open(log_path, "a+", newline="", encoding="utf-8") as f:
        f.seek(0)
        taken = {r.get("run_id") for r in csv.DictReader(f)}
        if run_id in taken:                 # same second as an earlier attempt
            suffix = 2
            while f"{run_id}-{suffix}" in taken:
                suffix += 1
            run_id = f"{run_id}-{suffix}"
        row["run_id"] = run_id

        f.seek(0, 2)
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS, lineterminator="\n")
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(row)

    return run_id


# --------------------------------------------------------------------- main


def main(argv):
    if not 2 <= len(argv) <= 3:
        print("Usage: python3 quiz.py EXAM.csv [RESULTS.csv]", file=sys.stderr)
        return 1
    exam_path = argv[1]
    log_path = argv[2] if len(argv) == 3 else DEFAULT_LOG

    try:
        meta, questions = load_exam(exam_path)
    except (OSError, ValueError) as err:
        print(f"Could not load the exam: {err}", file=sys.stderr)
        return 1

    passing = to_number(meta.get("passing_score_percentage"), DEFAULT_PASSING)
    duration = to_number(meta.get("duration_minutes"), 0) * 60

    print(rule("="))
    print(meta.get("title", "Quiz"), f"v{meta.get('version', '?')}")
    if meta.get("author"):
        print(f"by {meta['author']}")
    print(rule("="))
    print(f"{len(questions)} questions | pass mark {passing}%", end="")
    print(f" | hard time limit {clock(duration)}" if duration else " | no time limit")
    if duration:
        print("The clock starts once you enter your name and does not stop for the last question.")

    reader = Reader()
    try:
        candidate = reader.ask("\nYour name (press Enter to stay anonymous): ").strip()
    except Stop:
        return 1                    # closed stdin before starting
    candidate = candidate or "anonymous"

    records, seconds_used, completion = run_exam(questions, reader, duration)
    summary = report(records, meta, seconds_used, passing, completion)

    try:
        run_id = log_attempt(log_path, meta, candidate, summary, seconds_used)
        print(f"\nLogged to {log_path} as {run_id}")
    except OSError as err:
        print(f"\nCould not write the log: {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))