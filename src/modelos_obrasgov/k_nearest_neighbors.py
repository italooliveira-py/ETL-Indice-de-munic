"""K-Nearest Neighbors para risco adverso em obras públicas."""

from sklearn.neighbors import KNeighborsClassifier


GRADE = {
    "modelo__n_neighbors": [3, 5, 7, 11],
    "modelo__weights": ["uniform", "distance"],
    "modelo__p": [1, 2],
}


def criar(random_state: int) -> KNeighborsClassifier:
    del random_state
    return KNeighborsClassifier(algorithm="brute", n_jobs=1)
