from __future__ import annotations

from collections import Counter
from math import sqrt
import re


WORD_RE = re.compile(r"[a-z0-9_']+")


def tokenize(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def lexical_similarity(left: str, right: str) -> float:
    left_counts = Counter(tokenize(left))
    right_counts = Counter(tokenize(right))
    if not left_counts or not right_counts:
        return 0.0

    common = sum(left_counts[word] * right_counts[word] for word in set(left_counts) & set(right_counts))
    left_norm = sqrt(sum(value * value for value in left_counts.values()))
    right_norm = sqrt(sum(value * value for value in right_counts.values()))
    if not left_norm or not right_norm:
        return 0.0
    return common / (left_norm * right_norm)
