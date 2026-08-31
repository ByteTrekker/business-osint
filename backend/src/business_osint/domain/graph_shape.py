"""Reguły czytelności grafu — co jest strukturą, a co szumem.

Jednoosobowa działalność ma w naszym modelu dwa węzły: osobę i firmę, połączone
krawędzią „właściciel". Dla 614 948 wpisów oba mają **dosłownie tę samą nazwę**,
bo JDG bez nazwy handlowej nazywa się imieniem i nazwiskiem właściciela. Graf
pokazuje wtedy „Jacek Gadomski → właściciel → Jacek Gadomski", co nie niesie
żadnej informacji, a zajmuje węzeł.

Skala jest rozstrzygająca: **3 552 803 właścicieli ma dokładnie jedną firmę**,
a tylko 18 ma dwie. To nie jest brak danych, tylko prawo — osoba fizyczna może
mieć w CEIDG jeden wpis. Węzeł osoby przy JDG nie ma więc czego łączyć i nigdy
nie będzie miał.

Zwijamy **po stronie serwera**, nie w przeglądarce, bo budżet zapytania jest
częścią kontraktu (niezmiennik N3). Odsianie węzłów dopiero przy rysowaniu
oznaczałoby, że budżet płaci za wierzchołki, których nikt nie zobaczy — przy
depth 2 połowa wyniku potrafi być takimi duplikatami.

Nie usuwamy niczego z bazy. To jest decyzja o **prezentacji**: fakt, że osoba
prowadzi działalność, zostaje w grafie jako atrybut firmy i wraca w każdej innej
odpowiedzi API.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID


class _Node(Protocol):
    id: UUID
    entity_type: str


class _Edge(Protocol):
    source_id: UUID
    target_id: UUID
    relationship_type: str


#: Typ krawędzi, po której osoba wisi przy swojej jednoosobowej działalności.
SOLE_PROPRIETOR = "sole_proprietor_of"


def redundant_sole_trader_nodes(
    nodes: Iterable[_Node], edges: Iterable[_Edge], *, root_id: UUID
) -> set[UUID]:
    """Węzły osób, które nie wnoszą do grafu nic poza powtórzoną nazwą.

    Osoba jest zbędna, gdy w tym wyniku ma **dokładnie jedną** krawędź i jest to
    krawędź właściciela jednoosobowej działalności. Dwie krawędzie znaczą, że
    osoba coś łączy, i wtedy zostaje — takich właścicieli jest w bazie 18 i to
    właśnie oni są ciekawi.

    Korzeń nie jest nigdy zwijany. Jeżeli ktoś otworzył profil osoby, to o tę
    osobę pytał; usunięcie jej z własnego grafu byłoby odpowiedzią na inne
    pytanie niż zadane.

    Liczymy krawędzie **w obrębie zwróconego wyniku**, nie w całej bazie. Węzeł
    przycięty budżetem może mieć w bazie więcej powiązań, ale w tym grafie i tak
    ich nie widać, więc jego zwinięcie niczego nie ukrywa — a `truncated` mówi
    użytkownikowi, że wynik jest niepełny.
    """
    people = {node.id for node in nodes if node.entity_type == "person"} - {root_id}
    if not people:
        return set()

    degree: dict[UUID, int] = dict.fromkeys(people, 0)
    owner_edges: dict[UUID, int] = dict.fromkeys(people, 0)

    for edge in edges:
        for side in (edge.source_id, edge.target_id):
            if side in degree:
                degree[side] += 1
                if edge.relationship_type == SOLE_PROPRIETOR:
                    owner_edges[side] += 1

    return {person for person in people if degree[person] == 1 and owner_edges[person] == 1}
