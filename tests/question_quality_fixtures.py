"""Private synthetic misconception assets shared by authoring-verifier tests only."""

INCORRECT_SOLUTIONS = [
    {
        "position": 1,
        "label": "CONSTANT_OUTPUT",
        "source_code": 'def echo(word): return "hello" # PRIVATE_INCORRECT_CONSTANT',
    },
    {
        "position": 2,
        "label": "TRUNCATED_OUTPUT",
        "source_code": "def echo(word): return word[:5] # PRIVATE_INCORRECT_TRUNCATION",
    },
]
