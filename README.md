# exam-creater-n-taker-python

Create an exam, take it, and test your knowledge — all from the command line.

A dependency-free Python quiz runner. Exams are plain CSV files, so you can
write them in a spreadsheet, diff them in git, and version them like code.
Every attempt is appended to a results log with a unique run id, the date
completed, and the exam name and version.

No third-party packages. The standard library only:

| Script            | Imports                                |
| ----------------- | -------------------------------------- |
| `quiz.py`         | `csv` `queue` `sys` `threading` `time` |
| `json_to_csv.py`  | `csv` `json` `sys`                     |

Runs on Windows, macOS, and Linux with Python 3.8 or newer.

---

## Quick start

```bash
# take an existing exam (results go to quiz_results.csv)
python3 quiz.py python-basics_v1.2.csv

# ...or send the results somewhere specific
python3 quiz.py python-basics_v1.2.csv myTestResults.csv

# authoring: validate a JSON exam and convert it to CSV
python3 json_to_csv.py exam-python-basics.json python-basics_v1.3.csv
```

> **Note**
> Run `quiz.py` and pass the exam as an *argument*. Handing the CSV
> to Python directly (`python3 python-basics_v1.2.csv`) makes Python
> try to execute your data as source code and fails with
> `SyntaxError: invalid syntax` — the `#` metadata lines parse as comments,
> so the error lands on the first question row and looks like a data
> problem. In an IDE, the Run button runs *whichever file has focus*, so
> click into `quiz.py` first.

---

## Taking an exam

```
================================================================
Python Basics v1.1
by Arden Harrell
================================================================
13 questions | pass mark 85.0% | hard time limit 13:00
The clock starts once you enter your name and does not stop for the last question.

Your name (press Enter to stay anonymous):

----------------------------------------------------------------
Question 1 of 13  [Geek History]  time left 12:58
----------------------------------------------------------------
Who was the author of the Python programming language?

  A) Jillian Glopp -- snake bounty hunter
  B) Guido van Rossum -- author of ABC
  C) Elon Musk -- founder of SpaceX
  D) Walter Bright -- creator of D

Your answer (A/B/C/D), or 'skip' / 'quit':
```

At any prompt you can type `skip` to leave a question unanswered or `quit`
to end the attempt early. Both count as wrong, but the log records how many
questions you actually answered, so an abandoned attempt is distinguishable
from a failed one.

**Answers are matched generously.** Option keys are case-insensitive, and you
may type the option text instead of its key (`false` works as well as `F`).
Short answers ignore surrounding whitespace, letter case, and trailing
parentheses, so `print`, `Print`, and `print()` are all accepted.

**The clock is hard.** When `duration_minutes` runs out the attempt ends
immediately — including mid-question, with a half-typed answer discarded.
Set `duration_minutes` to `0`, or leave it out, for an untimed exam.

After the last question you get a per-question review showing the question
text, what you answered, and — when you got it wrong — the expected answer
and its explanation:

```
Q1 [Geek History] -- wrong
  Who was the author of the Python programming language?
  you said: C (Elon Musk -- founder of SpaceX)
  answer:   B (Guido van Rossum -- author of ABC)
  why:      Guido van Rossum is the creator of the Python programming language.
```

---

## Exam file format (CSV)

An exam is one CSV file in two parts: optional metadata lines, then the
questions.

```csv
# title: Python Basics
# version: 1.1
# author: Arden Harrell
# duration_minutes: 13
# passing_score_percentage: 85
id,type,subject,text,options,correct_answer,explanation
1,multiple-choice,Geek History,Who wrote Python?,A=Jillian Glopp|B=Guido van Rossum,B,Guido van Rossum created Python.
2,short-answer,Output,What built-in function shows output?,,print,The print() function displays output.
3,true-false,Python Syntax,Is this valid?,T=True|F=False,F,It prints the formatted string.
```

### Metadata

Leading lines beginning with `#` are read as `# key: value` and stop at the
header row. All are optional.

| Key                        | Effect                                                    |
| -------------------------- | --------------------------------------------------------- |
| `title`                    | Shown on the banner; slugged into the run id              |
| `version`                  | Shown on the banner; recorded in the log and the run id   |
| `author`                   | Shown on the banner                                       |
| `duration_minutes`         | Hard time limit. `0` or absent means untimed               |
| `passing_score_percentage` | Pass mark. Defaults to `70` if absent                     |

> **The version in the log comes from this metadata, not the filename.**
> A file named `...-v1.2.csv` whose metadata still says `# version: 1.1`
> logs its attempts as v1.1, which silently mixes them in with results from
> the older exam. Bump `# version:` whenever you add or change questions.

### Question columns

| Column           | Meaning                                                      |
| ---------------- | ------------------------------------------------------------ |
| `id`             | Shown in the review. Falls back to the CSV row number        |
| `type`           | `multiple-choice`, `true-false`, or `short-answer`           |
| `subject`        | Groups the per-subject breakdown. Defaults to `General`      |
| `text`           | The question. May span multiple lines (see below)            |
| `options`        | `KEY=text` pairs joined by `\|`. Empty for short answers     |
| `correct_answer` | The option key, or the accepted short answer(s)              |
| `explanation`    | Shown in the review when the answer was wrong                |

**Options** are encoded as `A=first|B=second|C=third`. Because `|` and `=`
are the separators, option *text* may not contain either character; the
converter rejects an exam that tries.

**Short answers** accept alternatives separated by `|`, so
`correct_answer` of `input|input()` marks both spellings correct.

**Multi-line questions** work: quote the field and double any inner quotes,
exactly as `csv` writes it. Code blocks survive intact and are re-indented
in the review.

```csv
3,true-false,Python Syntax,"Will this code provoke an error?

name, city = ""Cindy"", ""Seattle""
print(f""I am {name} from {city}."")",T=True|F=False,F,It prints the formatted string.
```

---

## Authoring in JSON

Hand-writing the `options` encoding is fiddly, so exams can be authored as
JSON and converted. `json_to_csv.py` validates first and writes nothing if
the exam would grade incorrectly.

```json
{
  "exam_meta": {
    "title": "Python Basics",
    "version": "1.1",
    "author": "Arden Harrell",
    "duration_minutes": 13,
    "passing_score_percentage": 85
  },
  "questions": [
    {
      "id": 1,
      "type": "multiple-choice",
      "subject": "Geek History",
      "text": "Who was the author of the Python programming language?",
      "options": [
        {"key": "A", "value": "Jillian Glopp -- snake bounty hunter"},
        {"key": "B", "value": "Guido van Rossum -- author of ABC"}
      ],
      "correct_answer": "B",
      "explanation": "Guido van Rossum is the creator of Python."
    }
  ]
}
```

Omitting the output path names the file from the title and version, e.g.
`python-basics_v1.1.csv`.

### Validation

Problems are reported in two tiers, and **every** problem is listed in one
pass so a single run tells you everything to fix.

*Errors* mean the exam would grade incorrectly or fail to load. Nothing is
written and the exit status is `1`:

- `correct_answer` matching no option key — *nobody could answer it correctly*
- a blank `correct_answer`, or one with an empty `|` alternative
- a missing or unrecognised `type`
- empty question `text` (the runner would skip the question silently)
- duplicate question ids, or duplicate option keys within a question
- option text containing `|` or `=`
- a choice question with fewer than two options
- `duration_minutes` or `passing_score_percentage` non-numeric or out of range

*Warnings* mean a default applies; the file is still written:

- no `subject` (grouped under `General`), `explanation`, or `id`
- missing `title`, `version`, `duration_minutes`, or `passing_score_percentage`
- `options` on a short-answer question (ignored by the runner)

```
$ python3 json_to_csv.py broken.json
warning: question 3 (id 3): no explanation; nothing will be shown in the review

broken.json has 2 problems; nothing was written:
  error: question 1 (id 1): correct_answer 'E' is not one of the option keys (A, B); nobody could answer this correctly
  error: question 2 (id 1): id already used by question 1
```

---

## Results log

Attempts are **appended** to the log, which is created with a header on
first write. One row per attempt:

| Column              | Example                                      |
| ------------------- | -------------------------------------------- |
| `run_id`            | `python-basics-v1.1-20261110-215138`         |
| `date_completed`    | `2026-11-10 21:51:38`                        |
| `exam_title`        | `Python Basics`                              |
| `version`           | `1.1`                                        |
| `candidate`         | `Bonnie` (or `anonymous`)                    |
| `questions`         | `13`                                         |
| `answered`          | `11` — excludes skipped and unreached         |
| `correct`           | `9`                                          |
| `percentage`        | `69.2`                                       |
| `passing_score`     | `85.0`                                       |
| `result`            | `PASS` / `FAIL`                              |
| `completion`        | `finished` / `timed_out` / `quit`            |
| `seconds_used`      | `312.4`                                      |
| `subject_breakdown` | `Geek History 1/1; Output 0/1`               |

The run id is `<slugged-title>-v<version>-<YYYYMMDD-HHMMSS>`. Because that
timestamp is only second-resolution, the log is read back before each write
and a `-2`, `-3` suffix is appended on collision, so ids stay unique even
when several attempts finish in the same second.

Since the log is append-only CSV, it loads straight into a spreadsheet or
pandas for pass rates and per-subject analysis.

---

## Repository layout

```
.
├── exam-python-basics.json        # JSON source for the current exam (13 questions)
├── json_to_csv.py                 # validator + JSON-to-CSV converter
├── quiz.py                        # the exam runner
├── python-basics_v1.2.csv         # current exam, 13 questions, 13 min
├── python-basics_v1.1.csv         #   earlier: 7 questions, 7 min
├── python-basics_v1.0.csv         #   earlier: 4 questions, 4 min
├── test.csv                       # 4-question scratch exam
├── python-basics-exam-v1.1.csv    # a results log, despite the name
└── myTestResults.csv              # results log
```

## How the timer works

`input()` cannot be interrupted, so the runner reads the keyboard on a
daemon thread that hands completed lines to the main thread over a
`queue.Queue`. The main thread waits only until the deadline; anything typed
after that is left unread, and because the thread is a daemon it never holds
up exit.

A thread is used rather than `select()` because `select()` cannot watch
stdin on Windows — only sockets. That one decision is what keeps the runner
cross-platform with no dependencies.

## Adding a question

1. Add it to `exam-python-basics.json`.
2. Bump `exam_meta.version` and, if needed, `duration_minutes`.
3. Convert: `python3 json_to_csv.py exam-python-basics.json python-basics_v1.3.csv`
4. Fix anything the validator reports, then take the exam once to proofread it.
