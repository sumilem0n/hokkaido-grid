#!/usr/bin/env python
"""Call http.get_text once and print what came back.

    .venv/bin/python -m tools.try_get http://127.0.0.1:8099/

Exists so the four runs are one command each instead of a here-doc. Prints
elapsed monotonic seconds because the sleeps are the thing being checked and
counting them off a wall clock is guesswork.
"""

import logging
import sys
import time

from hokkaido_grid.errors import SourceTransientError, SourceUnavailable
from hokkaido_grid.fetch import get_text


def main(argv):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    url = argv[1]
    start = time.monotonic()
    try:
        body = get_text(url, encoding=argv[2] if len(argv) > 2 else None)
    except (SourceTransientError, SourceUnavailable) as exc:
        print(f"\n{type(exc).__name__}: {exc}")
        print(f"status_code={getattr(exc, 'status_code', None)!r}")
        print(f"elapsed {time.monotonic() - start:.1f}s")
        return 1
    print(f"\nOK, {len(body)} chars in {time.monotonic() - start:.1f}s")
    print(body[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
