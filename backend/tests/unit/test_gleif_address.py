"""Rozkład adresu GLEIF na kolumny znaczące to samo co u pozostałych źródeł."""

from __future__ import annotations

from business_osint.domain.enums import EntityType
from business_osint.etl.sources.gleif_mapper import parse_lei_page


def _record(address: dict[str, object]) -> dict[str, object]:
    return {
        "data": [
            {
                "id": "X",
                "attributes": {
                    "lei": "X",
                    "entity": {"legalName": {"name": "TEST"}, "legalAddress": address},
                },
            }
        ]
    }


def _address(payload: dict[str, object]):
    parsed = parse_lei_page(payload)
    return next(e for e in parsed.entities if e.entity_type is EntityType.ADDRESS)


# Kształt wzięty z prawdziwej odpowiedzi GLEIF dla polskiego podmiotu: linia
# adresu zawiera miejscowość, ulicę i numer naraz, a numer jest **dodatkowo**
# w osobnym polu.
POLSKI_ADRES = {
    "city": "PŁOCK",
    "postalCode": "09-400",
    "country": "PL",
    "addressLines": ["PŁOCK BIELSKA 67"],
    "addressNumber": "67",
    "addressNumberWithinBuilding": "3",
}


def test_building_and_flat_come_from_their_own_fields() -> None:
    """GLEIF podaje numer osobno i trzeba go stamtąd wziąć.

    Wcześniej cała linia szła do kolumny `street`, a `building` zostawało puste.
    Ten sam adres z GLEIF i z CEIDG miał wtedy zupełnie inne kolumny.
    """
    address = _address(_record(POLSKI_ADRES))

    assert address.attributes["building"] == "67"
    assert address.attributes["unit"] == "3"


def test_city_and_number_are_stripped_from_the_street() -> None:
    """W kolumnie ulicy ma zostać ulica, a nie powtórzona miejscowość i numer."""
    assert _address(_record(POLSKI_ADRES)).attributes["street"] == "BIELSKA"


def test_display_uses_the_polish_form() -> None:
    """Zapis adresu ma być ten sam niezależnie od źródła."""
    assert _address(_record(POLSKI_ADRES)).display_name == "BIELSKA 67/3, 09-400 PŁOCK"


def test_address_without_a_number_still_parses() -> None:
    """Adres bez numeru budynku nie może wywrócić importu ani zgubić ulicy."""
    address = _address(
        _record({"city": "Płock", "postalCode": "09-400", "addressLines": ["Bielska"]})
    )

    assert address.attributes["street"] == "Bielska"
    assert address.attributes["building"] is None


def test_address_without_a_city_is_not_created() -> None:
    """Bez miejscowości adres jest niepowiązywalny z czymkolwiek."""
    parsed = parse_lei_page(_record({"postalCode": "09-400", "addressLines": ["Bielska 1"]}))

    assert [e for e in parsed.entities if e.entity_type is EntityType.ADDRESS] == []


def test_street_named_after_a_date_keeps_its_number() -> None:
    """„3 Maja 5" nie może stracić trójki — numer usuwamy tylko z końca linii."""
    address = _address(
        _record(
            {
                "city": "Płock",
                "postalCode": "09-400",
                "addressLines": ["3 Maja 5"],
                "addressNumber": "5",
            }
        )
    )

    assert address.attributes["street"] == "3 Maja"
