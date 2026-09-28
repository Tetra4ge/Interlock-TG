import time
from contextlib import contextmanager


from typing import Generator, Dict, Any

@contextmanager
def timer() -> Generator[Dict[str, Any], None, None]:
    """
    A context manager to track elapsed time in milliseconds.
    Usage:
        with timer() as t:
            do_something()
        print(f"Took {t['ms']} ms")
    """
    t = {"ms": 0}
    start = time.perf_counter()
    try:
        yield t
    finally:
        t["ms"] = int((time.perf_counter() - start) * 1000)
