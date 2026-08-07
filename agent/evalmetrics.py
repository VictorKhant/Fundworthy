"""How good is the ranking? Metrics, with no model and no network in them.

Split out of the calibration harness on purpose. `tests/calibration.py` decides whether
one particular set of fixtures passes; this decides what "passes" even means, and it has
to be callable from a unit test that never spends a penny.

The reason this file exists at all is that the old harness asserted exactly one thing —
every YES ranks above every NO — and that assertion was blind to the failure we actually
had. When the rubric put 60 of its 100 points on data most funder pages do not publish,
every score collapsed into 13–42 with six of eight findings inside a 7-point band. The
separation test still passed. A list where the top six are indistinguishable is a broken
ranking, and nothing in the suite could say so.

So there are four questions here, not one:

    separation    do the good ones outrank the bad ones          (correctness)
    spread        can you tell the good ones apart from each other  (usefulness)
    level         is the scale being used, or is everything at one end  (calibration)
    agreement     does the order match the order a human gave us   (ranking quality)

`spread` and `level` are the two that were missing, and they are the two that would have
caught this.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _ranks(values: list[float]) -> list[float]:
    """Ranks, with ties averaged.

    Ties matter here rather than being a footnote: a compressed score distribution
    produces a lot of them, and a tie-blind rank would flatter exactly the failure these
    metrics exist to detect.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    """Rank correlation, -1..1. 1.0 means the two orderings agree exactly.

    Computed from ranks via Pearson rather than the 1 - 6Σd²/n(n²-1) shortcut, because
    that shortcut is only correct when there are no ties — and ties are the norm here.
    """
    if len(a) != len(b):
        raise ValueError("spearman needs two series of the same length")
    if len(a) < 2:
        return 0.0
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if da == 0 or db == 0:
        # One side is entirely tied — every score identical. Not "perfectly correlated";
        # no information at all, which is a 0 and not a 1.
        return 0.0
    return num / (da * db)


def pair_accuracy(yes: list[float], no: list[float]) -> float:
    """Of every (good, bad) pair, what fraction did the scorer order correctly?

    This is AUC-ROC, computed the direct way. Written out as pairs rather than pulled
    from a library because with ten fixtures the definition is shorter than the import,
    and because the definition is the thing worth reading: *given one good grant and one
    bad one, how often does the scorer put them in the right order.*

    Kinder and far more informative than "did the worst YES beat the best NO": one
    misplaced fixture takes that assertion from pass to fail and tells you nothing about
    how close the rest were. A tie counts as half, because a tie is genuinely half-right.

    **With nothing to compare, the answer is 1.0, not 0.0.** There are no pairs, so no
    pair is out of order; reporting that as "0% of pairs ordered correctly" made a run
    where the free filters killed every bad fixture — a perfect run — fail on ordering.
    An empty question is not a wrong answer.
    """
    if not yes or not no:
        return 1.0
    wins = sum((y > n) + 0.5 * (y == n) for y in yes for n in no)
    return wins / (len(yes) * len(no))


@dataclass(frozen=True)
class Spread:
    """Whether a set of scores can tell its members apart."""

    n: int
    lo: int
    hi: int
    mean: float
    stdev: float
    band: int              # hi - lo
    window: int
    largest_cluster: int   # most scores inside any `window`-wide band

    @property
    def clustered_fraction(self) -> float:
        return self.largest_cluster / self.n if self.n else 0.0

    def __str__(self) -> str:
        return (f"n={self.n} range={self.lo}-{self.hi} (band {self.band}) "
                f"mean={self.mean:.1f} sd={self.stdev:.1f} "
                f"largest {self.window}pt cluster={self.largest_cluster}/{self.n}")


# A tenth of the scale. Scores closer together than this are, for a nonprofit deciding
# which two grants to read on a Thursday, the same score — so a run with most of its
# results inside one such band has not ranked anything, whatever its range looks like.
CLUSTER_WINDOW = 10


def spread(scores: list[int], *, window: int = CLUSTER_WINDOW) -> Spread:
    """Describe how much of the 0-100 scale a run actually used.

    `largest_cluster` is the one that catches the real failure, and it is why `band`
    alone is not enough. The pre-fix data was 42, 42, 42, 38, 38, 35, 28, 13: a band of
    29, which sounds healthy, held open entirely by one outlier at the bottom while six
    of the eight sat inside seven points of each other.

    The scan anchors a closed window at each observed score. That is exhaustive rather
    than a heuristic — the densest window of a fixed width can always be slid left until
    its lower edge meets a data point, so checking those positions checks all of them.
    """
    n = len(scores)
    if n == 0:
        return Spread(0, 0, 0, 0.0, 0.0, 0, window, 0)
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / n
    biggest = max(
        sum(1 for s in scores if anchor <= s <= anchor + window) for anchor in scores
    )
    return Spread(n=n, lo=min(scores), hi=max(scores), mean=mean,
                  stdev=math.sqrt(var), band=max(scores) - min(scores),
                  window=window, largest_cluster=biggest)


@dataclass(frozen=True)
class Report:
    separation: float      # worst YES minus best NO; >0 means cleanly separated
    pair_accuracy: float   # AUC-ROC, 0..1
    # Spearman against the expected ordering. Note the ceiling: the labels are binary, so
    # even a flawless ranking cannot reach 1.0 — with five yeses and three noes the best
    # attainable value is about 0.85, because the metric is being asked to reproduce ties
    # that the scores do not have. It is here to show *degradation*, and `pair_accuracy`
    # is the one to read for ordering quality. Both stay: this one becomes the primary
    # metric the day the fixtures carry a graded human rank instead of a yes/no.
    rank_agreement: float
    yes: Spread
    no: Spread
    overall: Spread

    def failures(self, *, min_pair_accuracy: float = 1.0,
                 max_clustered: float = 0.7,
                 headroom_above: int = 55) -> list[str]:
        """What is wrong, in sentences. Empty means the ranking is usable.

        Three thresholds, and each one is a lesson rather than a preference:

        `min_pair_accuracy` — the original assertion, restated so a near-miss reads as a
        near-miss instead of a hard fail.

        `max_clustered` — no more than this fraction of scores inside one window, whose
        width is `CLUSTER_WINDOW` and is reported rather than restated (it was written out
        as "5-point" here and in the failure string while the window was in fact 10, so
        the two things a single run printed disagreed with each other). This is the guard
        the suite did not have. Six of eight findings within 7 points is a list whose
        order is noise, and it passed every test in the repo.

        `headroom_above` — at least one clear YES has to clear this. A scale where the
        best possible opportunity scores 42 is not strict, it is broken: it means points
        are being deducted for evidence the funder never published, and it is the exact
        symptom that started this investigation.
        """
        out: list[str] = []
        if self.pair_accuracy < min_pair_accuracy:
            out.append(
                f"ordering: {self.pair_accuracy:.0%} of good/bad pairs are ordered "
                f"correctly (want {min_pair_accuracy:.0%}). Separation is "
                f"{self.separation:+.0f}."
            )
        if self.overall.clustered_fraction > max_clustered:
            out.append(
                f"discrimination: {self.overall.largest_cluster} of {self.overall.n} "
                f"scores sit inside one {self.overall.window}-point window — the ranking "
                f"cannot tell them apart. {self.overall}"
            )
        if self.yes.n and self.yes.hi < headroom_above:
            out.append(
                f"headroom: the best clear-yes scored {self.yes.hi}, under {headroom_above}. "
                "A rubric where an obviously good grant cannot clear the middle of the "
                "scale is deducting points for evidence the funder never published."
            )
        return out


def report(yes_scores: list[int], no_scores: list[int]) -> Report:
    """The whole picture from one run of a labelled set."""
    yes_s, no_s = list(yes_scores), list(no_scores)
    expected = [1.0] * len(yes_s) + [0.0] * len(no_s)
    actual = [float(s) for s in yes_s + no_s]
    return Report(
        separation=(min(yes_s) - max(no_s)) if (yes_s and no_s) else 0.0,
        pair_accuracy=pair_accuracy([float(s) for s in yes_s],
                                    [float(s) for s in no_s]),
        rank_agreement=spearman(actual, expected),
        yes=spread(yes_s),
        no=spread(no_s),
        overall=spread(yes_s + no_s),
    )
