"""Ochrona przed eksplozją grafu.

Problem: w polskich danych istnieją huby — adres z 5 tys. spółek (wirtualne biura),
syndyk w 300 spółkach, Skarb Państwa jako udziałowiec. Naiwne BFS na głębokość 3
z takiego węzła zwraca pół bazy i zabija zarówno bazę, jak i przeglądarkę.

Reguła: nigdy nie zwracamy więcej niż ``max_nodes``; huby pokazujemy jako
pojedynczy węzeł zbiorczy z licznikiem, nie rozwijamy ich automatycznie.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Powyżej tylu krawędzi węzeł traktujemy jak hub i nie rozwijamy go dalej.
DEFAULT_HUB_DEGREE = 150


@dataclass(frozen=True, slots=True)
class GraphBudget:
    """Twarde limity pojedynczego zapytania o sąsiedztwo."""

    max_depth: int = 2
    max_nodes: int = 300
    fanout_per_node: int = 25
    hub_degree: int = DEFAULT_HUB_DEGREE

    @classmethod
    def for_plan(cls, plan: str) -> GraphBudget:
        """Limity zależne od planu — to jest miejsce, w którym monetyzuje się głębokość."""
        match plan:
            case "free":
                return cls(max_depth=1, max_nodes=75, fanout_per_node=15)
            case "pro":
                return cls(max_depth=3, max_nodes=1_000, fanout_per_node=50)
            case "b2b":
                return cls(max_depth=4, max_nodes=5_000, fanout_per_node=200)
            case _:
                return cls()

    def clamp_depth(self, requested: int | None) -> int:
        if requested is None:
            return min(2, self.max_depth)
        return max(1, min(requested, self.max_depth))


@dataclass(slots=True)
class ExpansionState:
    """Stan BFS: co już odwiedzono, ile budżetu zostało, co przycięto."""

    budget: GraphBudget
    visited: set[str]
    truncated: bool = False
    suppressed_hubs: int = 0

    @classmethod
    def start(cls, root_id: str, budget: GraphBudget) -> ExpansionState:
        return cls(budget=budget, visited={root_id})

    @property
    def remaining_nodes(self) -> int:
        return max(0, self.budget.max_nodes - len(self.visited))

    def should_expand(self, entity_id: str, degree: int) -> bool:
        """Czy rozwijać ten węzeł w kolejnym poziomie."""
        if degree > self.budget.hub_degree:
            self.suppressed_hubs += 1
            return False
        return True

    def accept(self, entity_ids: list[str]) -> list[str]:
        """Dokłada nowe węzły do odwiedzonych, respektując budżet.

        Zwraca faktycznie przyjęte identyfikatory; ustawia ``truncated``,
        jeżeli cokolwiek zostało odrzucone.
        """
        accepted: list[str] = []
        for entity_id in entity_ids:
            if entity_id in self.visited:
                continue
            if len(self.visited) >= self.budget.max_nodes:
                self.truncated = True
                break
            self.visited.add(entity_id)
            accepted.append(entity_id)
        return accepted
