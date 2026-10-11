"""Runs ONLY inside isolation. Contains no expected answers or worker credentials."""

import contextlib
import errno
import json
import sys
from typing import Any


def main() -> None:
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    payload = json.loads(sys.stdin.buffer.readline(131073))
    namespace: dict[str, Any] = {"__name__": "learner"}
    try:
        code = compile(payload["source"], "submission.py", "exec")
    except SyntaxError:
        raise SystemExit(65) from None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            exec(code, namespace)
            value = namespace[payload["function"]](*payload["input"])
            output = json.dumps(value, allow_nan=False, separators=(",", ":"))
        sys.stdout.write(output + "\n")
    except MemoryError:
        raise SystemExit(71) from None
    except OSError as error:
        raise SystemExit(71 if error.errno == errno.ENOSPC else 70) from None
    except BaseException:
        raise SystemExit(70) from None


if __name__ == "__main__":
    main()
