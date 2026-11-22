"""Side-by-side configuration diff (R3.4), computed on the server.

A line-for-line port of the web's former `web/src/lib/diff.ts` (LCS table, deletions before
additions on ties, adjacent deletions/additions paired into "changed" rows). Parity with the
TypeScript is checked against fixtures captured from it (tests/fixtures/diff_parity.json).

The only addition is skipping the shared leading lines when filling the LCS table: the walk
emits those as "same" rows without reading the table, so the output is unchanged.
"""

import re
from array import array
from typing import Any

MAX_DIFF_LINES = 5000  # per side; bounds the O(n*m) table


class DiffTooLargeError(ValueError):
    """A configuration has more lines than the diff will compare."""


def _lines(text: str) -> list[str]:
    return [] if text == "" else re.split(r"\r?\n", text)


def side_by_side(a: str, b: str) -> dict[str, Any]:
    left, right = _lines(a), _lines(b)
    if max(len(left), len(right)) > MAX_DIFF_LINES:
        raise DiffTooLargeError(
            f"These configurations are too large to compare here (over {MAX_DIFF_LINES} lines). "
            "Compare a smaller pair of versions, or download both and diff them locally."
        )
    n, m = len(left), len(right)
    prefix = 0
    while prefix < n and prefix < m and left[prefix] == right[prefix]:
        prefix += 1

    # lcs[i][j] = LCS length of left[i:] and right[j:]; rows before `prefix` are never read.
    lcs: list[array[int]] = [array("I")] * prefix + [
        array("I", bytes(4 * (m + 1))) for _ in range(prefix, n + 1)
    ]
    for i in range(n - 1, prefix - 1, -1):
        row, below, text = lcs[i], lcs[i + 1], left[i]
        for j in range(m - 1, prefix - 1, -1):
            if text == right[j]:
                row[j] = below[j + 1] + 1
            else:
                down, across = below[j], row[j + 1]
                row[j] = down if down >= across else across

    rows: list[dict[str, Any]] = []
    i = j = added = removed = 0
    while i < n or j < m:
        if i < n and j < m and left[i] == right[j]:
            rows.append(
                {
                    "kind": "same",
                    "left": {"n": i + 1, "text": left[i]},
                    "right": {"n": j + 1, "text": right[j]},
                }
            )
            i += 1
            j += 1
            continue
        deletions: list[dict[str, Any]] = []
        additions: list[dict[str, Any]] = []
        while (i < n or j < m) and not (i < n and j < m and left[i] == right[j]):
            if i < n and (j == m or lcs[i + 1][j] >= lcs[i][j + 1]):
                deletions.append({"n": i + 1, "text": left[i]})
                i += 1
                removed += 1
            else:
                additions.append({"n": j + 1, "text": right[j]})
                j += 1
                added += 1
        for k in range(max(len(deletions), len(additions))):
            row_out: dict[str, Any] = {}
            if k < len(deletions):
                row_out["left"] = deletions[k]
            if k < len(additions):
                row_out["right"] = additions[k]
            row_out["kind"] = (
                "changed" if len(row_out) == 2 else "removed" if "left" in row_out else "added"
            )
            rows.append(row_out)
    return {"rows": rows, "added": added, "removed": removed}
