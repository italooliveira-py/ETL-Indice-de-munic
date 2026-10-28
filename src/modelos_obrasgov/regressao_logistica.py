"""Regressão Logística regularizada para risco adverso em obras públicas."""

from sklearn.linear_model import LogisticRegression


GRADE = {
    "modelo__C": [0.01, 0.1, 1.0, 10.0],
    "modelo__class_weight": [None, "balanced"],
}


def criar(random_state: int) -> LogisticRegression:
    return LogisticRegression(max_iter=2_000, random_state=random_state)
