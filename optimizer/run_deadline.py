"""Time-budget checks between simulations, with room to save the best case."""

from datetime import datetime


def parse_deadline(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("optimization.end_at must include its timezone")
    return parsed.timestamp()


def budget_exhausted(deadline, now, longest_simulation, save_best=True):
    if deadline is None:
        return False
    # One prospective solve, one best-case solve, plus saving overhead.
    reserve = max(300.0, longest_simulation * (2.5 if save_best else 1.25) + 120.0)
    return now + reserve >= deadline
