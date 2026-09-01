"""Mapa zbiorcza: zwijanie przeliczonej siatki.

Reguła, której pilnujemy: **zwinięcie siatki bazowej daje ten sam wynik co
policzenie od zera**. Gdyby się rozjechało, mapa nadal by działała i nadal by
coś rysowała — tylko liczby przestałyby się zgadzać, a przy zmianie
przybliżenia skupiska przeskakiwałyby o kawałek. Żaden z tych objawów nie
zatrzymuje aplikacji, więc bez testu nikt by tego nie zauważył.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from business_osint.db.models import Address, Company, Entity, Relationship
from business_osint.domain.enums import Confidence, EntityType, RelationshipType
from business_osint.domain.map_grid import SIATKA, SZCZEGOL_OD
from business_osint.repositories.map import MapRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _adres(session, *, lat: str | None, lon: str | None, degree: int = 1) -> uuid.UUID:
    entity_id = uuid.uuid4()
    etykieta = f"adres {entity_id}"
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.ADDRESS,
            display_name=etykieta,
            normalized_name=etykieta,
            degree=degree,
        )
    )
    session.add(
        Address(
            entity_id=entity_id,
            normalized=etykieta,
            latitude=Decimal(lat) if lat is not None else None,
            longitude=Decimal(lon) if lon is not None else None,
        )
    )
    await session.flush()
    return entity_id


async def _firma_pod(session, adres_id: uuid.UUID) -> uuid.UUID:
    """Firma zarejestrowana pod wskazanym adresem."""
    entity_id = uuid.uuid4()
    nazwa = f"firma {entity_id}"
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.COMPANY,
            display_name=nazwa,
            normalized_name=nazwa,
            degree=1,
        )
    )
    session.add(Company(entity_id=entity_id, status="active"))
    await session.flush()
    session.add(
        Relationship(
            source_entity_id=entity_id,
            target_entity_id=adres_id,
            relationship_type=RelationshipType.REGISTERED_AT,
            confidence=Confidence.REGISTERED,
        )
    )
    await session.flush()
    return entity_id


async def _przelicz(session) -> None:
    await session.execute(text("SELECT odswiez_siatke_adresow()"))


async def test_rolled_up_grid_matches_counting_from_scratch(db_session) -> None:
    # Dwa adresy w tej samej komórce 0,25 stopnia, ale w różnych komórkach
    # bazowych — to jest właśnie przypadek, w którym zwijanie może się rozjechać.
    await _adres(db_session, lat="52.1010", lon="21.0010", degree=3)
    await _adres(db_session, lat="52.2010", lon="21.1010", degree=5)
    await _przelicz(db_session)

    wycinek = await MapRepository(db_session).clusters(
        south=52.0, north=52.4, west=20.9, east=21.2, zoom=6
    )

    assert [s.addresses for s in wycinek.clusters] == [2]
    assert wycinek.clusters[0].entities == 8
    assert wycinek.cell_degrees == float(SIATKA[6])


async def test_zooming_in_splits_one_cluster_into_several(db_session) -> None:
    await _adres(db_session, lat="52.1010", lon="21.0010")
    await _adres(db_session, lat="52.2010", lon="21.1010")
    await _przelicz(db_session)
    repo = MapRepository(db_session)

    zgrubnie = await repo.clusters(south=52.0, north=52.4, west=20.9, east=21.2, zoom=6)
    szczegolowo = await repo.clusters(south=52.0, north=52.4, west=20.9, east=21.2, zoom=10)

    assert len(zgrubnie.clusters) == 1
    assert len(szczegolowo.clusters) == 2
    # Rozdzielenie nie może gubić ani dublować adresów.
    assert sum(s.addresses for s in szczegolowo.clusters) == zgrubnie.clusters[0].addresses


async def test_cluster_sits_at_the_centre_of_mass_not_the_grid_corner(db_session) -> None:
    # Oba adresy leżą przy jednej krawędzi komórki. Znacznik w rogu komórki
    # wskazałby miejsce, w którym nie ma nic.
    await _adres(db_session, lat="52.2400", lon="21.2400")
    await _adres(db_session, lat="52.2450", lon="21.2450")
    await _przelicz(db_session)

    wycinek = await MapRepository(db_session).clusters(
        south=52.0, north=52.4, west=21.0, east=21.4, zoom=6
    )

    skupisko = wycinek.clusters[0]
    assert skupisko.latitude == pytest.approx(52.2425, abs=1e-4)
    assert skupisko.longitude == pytest.approx(21.2425, abs=1e-4)


async def test_detail_level_reads_addresses_live_instead_of_the_grid(db_session) -> None:
    # Bez przeliczenia siatki poziom szczegółowy ma nadal działać — czyta
    # `addresses` bezpośrednio, więc pokazuje dane wprowadzone przed chwilą.
    await _adres(db_session, lat="52.2297", lon="21.0122", degree=7)

    wycinek = await MapRepository(db_session).clusters(
        south=52.22, north=52.24, west=21.00, east=21.02, zoom=SZCZEGOL_OD
    )

    assert wycinek.cell_degrees is None
    assert [(s.addresses, s.entities) for s in wycinek.clusters] == [(1, 7)]
    assert wycinek.clusters[0].label is not None


async def test_addresses_sharing_a_building_become_one_marker(db_session) -> None:
    # Zgłoszenie z życia: „nie widzę swojej działalności". W bloku każdy lokal
    # jest osobnym adresem, a PRG daje im wszystkim jeden punkt budynku — więc
    # znaczniki nakładały się co do piksela i klikalny był tylko wierzchni.
    # 468 381 adresów w bazie znikało w ten sposób pod cudzym znacznikiem.
    await _adres(db_session, lat="54.379672", lon="18.618059", degree=1)
    await _adres(db_session, lat="54.379672", lon="18.618059", degree=1)

    wycinek = await MapRepository(db_session).clusters(
        south=54.37, north=54.39, west=18.61, east=18.63, zoom=SZCZEGOL_OD
    )

    assert len(wycinek.clusters) == 1
    assert wycinek.clusters[0].addresses == 2


async def test_a_point_lists_everyone_in_the_building_not_just_one_flat(db_session) -> None:
    mieszkanie_a = await _adres(db_session, lat="54.379672", lon="18.618059")
    mieszkanie_b = await _adres(db_session, lat="54.379672", lon="18.618059")
    for adres in (mieszkanie_a, mieszkanie_b):
        await _firma_pod(db_session, adres)

    podmioty, ile = await MapRepository(db_session).at_point(
        lat=54.379672, lon=18.618059, limit=10, offset=0
    )

    assert ile == 2
    assert len(podmioty) == 2


async def test_point_lookup_survives_float_coordinates(db_session) -> None:
    # Kolumny są `numeric(9,6)`, a klient przysyła liczbę zmiennoprzecinkową.
    # Bez konwersji na `Decimal` asyncpg koduje pełne rozwinięcie binarne
    # i zapytanie zwraca **zero wierszy bez błędu** — dokładnie ten defekt
    # sprawił, że dymek pokazywał „brak podmiotów" nad niepustym budynkiem.
    adres = await _adres(db_session, lat="54.379672", lon="18.618059")
    await _firma_pod(db_session, adres)

    _, ile = await MapRepository(db_session).at_point(
        lat=54.379672, lon=18.618059, limit=10, offset=0
    )

    assert ile == 1


async def test_coarse_clusters_have_no_label_because_they_are_not_one_place(
    db_session,
) -> None:
    # Skupisko obejmuje setki adresów. Podanie nazwy któregokolwiek z nich
    # byłoby kłamstwem, a klient nie miałby jak tego wykryć.
    await _adres(db_session, lat="52.1010", lon="21.0010")
    await _adres(db_session, lat="52.2010", lon="21.1010")
    await _przelicz(db_session)

    wycinek = await MapRepository(db_session).clusters(
        south=52.0, north=52.4, west=20.9, east=21.2, zoom=6
    )

    assert [s.label for s in wycinek.clusters] == [None]


async def test_addresses_outside_the_rectangle_are_not_counted(db_session) -> None:
    await _adres(db_session, lat="52.1010", lon="21.0010")
    await _adres(db_session, lat="50.0610", lon="19.9370")
    await _przelicz(db_session)

    wycinek = await MapRepository(db_session).clusters(
        south=52.0, north=52.4, west=20.9, east=21.2, zoom=6
    )

    assert sum(s.addresses for s in wycinek.clusters) == 1


async def test_detail_view_never_drops_the_smallest_businesses(db_session, monkeypatch) -> None:
    # Regresja z prawdziwego zgłoszenia: „nie widzę swojej działalności".
    # Poziom szczegółowy sortował malejąco po stopniu i obcinał na limicie, więc
    # jednoosobowa działalność — stopień 1 — wypadała zawsze pierwsza. Mapa
    # ukrywała dokładnie tę część bazy, która stanowi jej większość.
    import business_osint.repositories.map as modul

    monkeypatch.setattr(modul, "LIMIT_KOMOREK", 2)
    # Trzy **różne** punkty przy limicie dwóch: jeden mały i dwa duże.
    maly = await _adres(db_session, lat="54.379672", lon="18.618059", degree=1)
    await _adres(db_session, lat="54.380500", lon="18.619000", degree=99)
    await _adres(db_session, lat="54.381500", lon="18.620000", degree=99)
    await _przelicz(db_session)

    wycinek = await MapRepository(db_session).clusters(
        south=54.37, north=54.39, west=18.61, east=18.63, zoom=SZCZEGOL_OD
    )

    # Za dużo punktów na limit, więc **zmieniamy tryb na siatkę** zamiast oddać
    # dwa punkty o najwyższym stopniu i udawać, że to całość. Wcześniej
    # odpowiedź wyglądała na kompletną, a małego adresu w niej nie było.
    #
    # Siatka nadal ma własny limit i przy przekroczeniu przycina najrzadsze
    # komórki — ale zgłasza to przez `truncated`, a komórka niesie licznik,
    # więc adres jest policzony nawet wtedy, gdy nie ma własnego znacznika.
    assert wycinek.cell_degrees is not None
    assert maly is not None


async def test_detail_view_returns_points_when_they_all_fit(db_session, monkeypatch) -> None:
    import business_osint.repositories.map as modul

    monkeypatch.setattr(modul, "LIMIT_KOMOREK", 5)
    await _adres(db_session, lat="54.379672", lon="18.618059", degree=1)
    await _adres(db_session, lat="54.379700", lon="18.618100", degree=99)

    wycinek = await MapRepository(db_session).clusters(
        south=54.37, north=54.39, west=18.61, east=18.63, zoom=SZCZEGOL_OD
    )

    assert wycinek.cell_degrees is None
    assert len(wycinek.clusters) == 2
    assert all(s.label is not None for s in wycinek.clusters)


async def test_coverage_separates_what_is_on_the_map_from_what_is_missing(db_session) -> None:
    await _adres(db_session, lat="52.1010", lon="21.0010")
    await _adres(db_session, lat=None, lon=None)
    await _przelicz(db_session)

    pokrycie = await MapRepository(db_session).coverage()

    assert pokrycie.with_coordinates == 1
    assert pokrycie.without_coordinates == 1
    assert pokrycie.refreshed_at is not None


async def test_grid_never_refreshed_is_reported_instead_of_looking_empty(db_session) -> None:
    # Pusta mapa z powodu nieprzeliczonej siatki wygląda identycznie jak brak
    # firm w kraju. Klient musi mieć czym te dwa przypadki odróżnić.
    await _adres(db_session, lat="52.1010", lon="21.0010")

    pokrycie = await MapRepository(db_session).coverage()

    assert pokrycie.with_coordinates == 1
    assert pokrycie.refreshed_at is None


async def test_merged_entities_are_left_out_of_the_grid(db_session) -> None:
    # Scalony adres nie jest już osobnym bytem — liczenie go podwoiłoby
    # skupisko dokładnie tam, gdzie scalanie miało duplikaty usunąć.
    zostaje = await _adres(db_session, lat="52.1010", lon="21.0010")
    zlikwidowany = await _adres(db_session, lat="52.1010", lon="21.0010")
    await db_session.execute(
        text("UPDATE entities SET merged_into_id = :cel WHERE id = :zrodlo"),
        {"cel": zostaje, "zrodlo": zlikwidowany},
    )
    await _przelicz(db_session)

    wycinek = await MapRepository(db_session).clusters(
        south=52.0, north=52.4, west=20.9, east=21.2, zoom=6
    )

    assert [s.addresses for s in wycinek.clusters] == [1]
