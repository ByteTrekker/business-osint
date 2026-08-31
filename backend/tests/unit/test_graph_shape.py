"""Reguła zwijania węzłów osób prowadzących jednoosobową działalność."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from business_osint.domain.graph_shape import redundant_sole_trader_nodes


@dataclass
class Node:
    id: uuid.UUID
    entity_type: str


@dataclass
class Edge:
    source_id: uuid.UUID
    target_id: uuid.UUID
    relationship_type: str


ROOT = uuid.uuid4()
OSOBA = uuid.uuid4()
FIRMA = uuid.uuid4()
INNA = uuid.uuid4()


def test_person_holding_only_her_sole_proprietorship_is_collapsed() -> None:
    """Osoba z jedną krawędzią właściciela nie wnosi nic poza powtórzoną nazwą.

    Graf pokazuje wtedy „Jan Kowalski → właściciel → Jan Kowalski". Dla 614 948
    wpisów obie nazwy są dosłownie identyczne.
    """
    nodes = [Node(ROOT, "company"), Node(OSOBA, "person")]
    edges = [Edge(OSOBA, ROOT, "sole_proprietor_of")]

    assert redundant_sole_trader_nodes(nodes, edges, root_id=ROOT) == {OSOBA}


def test_person_connecting_two_things_is_kept() -> None:
    """Osoba z dwiema krawędziami coś łączy — i to jest właśnie ciekawe.

    Takich właścicieli jest w bazie 18 na 3,55 mln. Zwinięcie ich ukryłoby
    jedyne przypadki, dla których warstwa osobowa w ogóle istnieje.
    """
    nodes = [Node(ROOT, "company"), Node(OSOBA, "person"), Node(INNA, "company")]
    edges = [
        Edge(OSOBA, ROOT, "sole_proprietor_of"),
        Edge(OSOBA, INNA, "sole_proprietor_of"),
    ]

    assert redundant_sole_trader_nodes(nodes, edges, root_id=ROOT) == set()


def test_root_person_is_never_collapsed() -> None:
    """Kto otworzył profil osoby, o tę osobę pytał.

    Usunięcie korzenia z jego własnego grafu byłoby odpowiedzią na inne pytanie
    niż zadane.
    """
    nodes = [Node(OSOBA, "person"), Node(FIRMA, "company")]
    edges = [Edge(OSOBA, FIRMA, "sole_proprietor_of")]

    assert redundant_sole_trader_nodes(nodes, edges, root_id=OSOBA) == set()


def test_person_attached_by_another_kind_of_edge_is_kept() -> None:
    """Zwijamy wyłącznie właściciela JDG, nie każdą osobę o jednej krawędzi.

    Członek zarządu z jedną krawędzią jest osobnym bytem i jego węzeł niesie
    informację, której firma nie powtarza.
    """
    nodes = [Node(ROOT, "company"), Node(OSOBA, "person")]
    edges = [Edge(OSOBA, ROOT, "board_member_of")]

    assert redundant_sole_trader_nodes(nodes, edges, root_id=ROOT) == set()


def test_company_nodes_are_never_collapsed() -> None:
    """Reguła dotyczy osób. Firma z jedną krawędzią zostaje firmą."""
    nodes = [Node(ROOT, "company"), Node(FIRMA, "company")]
    edges = [Edge(FIRMA, ROOT, "sole_proprietor_of")]

    assert redundant_sole_trader_nodes(nodes, edges, root_id=ROOT) == set()


def test_edge_direction_does_not_matter() -> None:
    """Krawędź liczy się niezależnie od tego, po której stronie stoi osoba.

    Widok grafu jest dwukierunkowy, więc ta sama relacja przychodzi raz jako
    wychodząca, raz jako przychodząca.
    """
    nodes = [Node(ROOT, "company"), Node(OSOBA, "person")]
    edges = [Edge(ROOT, OSOBA, "sole_proprietor_of")]

    assert redundant_sole_trader_nodes(nodes, edges, root_id=ROOT) == {OSOBA}


def test_graph_without_people_needs_no_work() -> None:
    """Brak osób w wyniku ma dawać pusty zbiór, bez przechodzenia po krawędziach."""
    nodes = [Node(ROOT, "company"), Node(FIRMA, "company")]

    assert redundant_sole_trader_nodes(nodes, [], root_id=ROOT) == set()


def test_person_with_no_edges_at_all_is_kept() -> None:
    """Osoba bez krawędzi w wyniku nie jest „powtórzeniem firmy" — nie ma czego zwijać.

    Zwinięcie takiego węzła usunęłoby go bez zastąpienia czymkolwiek, czyli
    ukryłoby fakt zamiast go uprościć.
    """
    nodes = [Node(ROOT, "company"), Node(OSOBA, "person")]

    assert redundant_sole_trader_nodes(nodes, [], root_id=ROOT) == set()


def test_person_with_a_second_edge_of_another_kind_is_kept() -> None:
    """Właściciel JDG, który jest też członkiem zarządu gdzie indziej, zostaje.

    Sam licznik krawędzi właściciela tego nie wyłapie — wynosi jeden w obu
    przypadkach. Rozstrzyga dopiero **całkowita** liczba krawędzi: osoba, która
    dotyka czegoś jeszcze, przestaje być powtórzeniem nazwy własnej firmy.
    """
    nodes = [Node(ROOT, "company"), Node(OSOBA, "person"), Node(INNA, "company")]
    edges = [
        Edge(OSOBA, ROOT, "sole_proprietor_of"),
        Edge(OSOBA, INNA, "board_member_of"),
    ]

    assert redundant_sole_trader_nodes(nodes, edges, root_id=ROOT) == set()
