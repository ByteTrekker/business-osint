"""Odczyt punktów adresowych z GML-a PRG.

Fixture to **skrócony, ale niezmieniony** fragment prawdziwego pliku z rejestru:
struktura, przestrzenie nazw i zapis współrzędnych są takie, jak w oryginale.
Uproszczenie któregokolwiek z nich zamieniłoby ten test w opis formatu, który
sobie wyobrażam, zamiast tego, który przysyła GUGiK.
"""

from __future__ import annotations

import pathlib

from business_osint.etl.sources.prg import czytaj_punkty

FRAGMENT = """<?xml version="1.0" encoding="UTF-8"?>
<gml:FeatureCollection xmlns:gml="http://www.opengis.net/gml/3.2"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:prgad="https://geoportal.gov.pl/schemas/prgad/1.0">
  <gml:featureMember>
    <prgad:AD_Miejscowosc gml:id="M1">
      <prgad:nazwa>Chyrzyno</prgad:nazwa>
      <prgad:identyfikatorSIMC>0181728</prgad:identyfikatorSIMC>
      <prgad:TERYTGminy>0805022</prgad:TERYTGminy>
    </prgad:AD_Miejscowosc>
  </gml:featureMember>
  <gml:featureMember>
    <prgad:AD_UlicaPlac gml:id="U1">
      <prgad:nazwaPelna>Plac Kasztanowy</prgad:nazwaPelna>
      <prgad:identyfikatorULIC>08173</prgad:identyfikatorULIC>
    </prgad:AD_UlicaPlac>
  </gml:featureMember>
  <gml:featureMember>
    <prgad:AD_PunktAdresowy gml:id="P1">
      <prgad:numerPorzadkowy>43</prgad:numerPorzadkowy>
      <prgad:georeferencja>
        <gml:Point srsName="EPSG:2180"><gml:pos>205249.1 530976.79</gml:pos></gml:Point>
      </prgad:georeferencja>
      <prgad:kodPocztowy>68-213</prgad:kodPocztowy>
      <prgad:miejscowosc xlink:href="#M1"/>
      <prgad:ulica2 xlink:href="#U1"/>
    </prgad:AD_PunktAdresowy>
  </gml:featureMember>
  <gml:featureMember>
    <prgad:AD_PunktAdresowy gml:id="P2">
      <prgad:numerPorzadkowy>7</prgad:numerPorzadkowy>
      <prgad:georeferencja>
        <gml:Point srsName="EPSG:2180"><gml:pos>205249.1 530976.79</gml:pos></gml:Point>
      </prgad:georeferencja>
      <prgad:miejscowosc xlink:href="#M1"/>
    </prgad:AD_PunktAdresowy>
  </gml:featureMember>
  <gml:featureMember>
    <prgad:AD_PunktAdresowy gml:id="P3">
      <prgad:numerPorzadkowy>9</prgad:numerPorzadkowy>
      <prgad:miejscowosc xlink:href="#M1"/>
    </prgad:AD_PunktAdresowy>
  </gml:featureMember>
</gml:FeatureCollection>
"""


def _punkty(tmp_path: pathlib.Path, tresc: str = FRAGMENT):
    plik = tmp_path / "prg.gml"
    plik.write_text(tresc, encoding="utf-8")
    return list(czytaj_punkty(plik))


def test_coordinates_are_read_as_easting_northing(tmp_path) -> None:
    """To jest najważniejszy test w tym pliku.

    PRG deklaruje `EPSG:2180`, którego urzędowa kolejność osi to
    (northing, easting), ale zapisuje współrzędne odwrotnie. Odczyt zgodny ze
    specyfikacją umieszcza Chyrzyno w Małopolsce, 350 km od miejsca, które
    opisuje — i nadal w Polsce, więc żadne sprawdzenie „czy punkt jest
    w kraju" tego nie wyłapie.
    """
    punkt = _punkty(tmp_path)[0]

    assert round(punkt.latitude, 3) == 52.565
    assert round(punkt.longitude, 3) == 14.649


def test_names_are_resolved_through_xlink_references(tmp_path) -> None:
    """Punkt nie zawiera nazw — trzyma referencje do osobnych obiektów.

    Bez ich rozwiązania punkt adresowy nie ma z czym się dopasować. To także
    powód, dla którego nie używamy tu DuckDB ani GDAL-a: czytają GML, ale
    `xlink` zostawiają nierozwiązany.
    """
    punkt = _punkty(tmp_path)[0]

    assert punkt.city == "Chyrzyno"
    assert punkt.street == "Plac Kasztanowy"
    assert punkt.building == "43"


def test_official_identifiers_are_carried_over(tmp_path) -> None:
    """TERYT, SIMC i ULIC to twarde klucze administracyjne, których nie mamy skądinąd."""
    punkt = _punkty(tmp_path)[0]

    assert (punkt.teryt, punkt.simc, punkt.ulic) == ("0805022", "0181728", "08173")


def test_rural_address_without_a_street_is_still_read(tmp_path) -> None:
    """Adres bez ulicy to nie brak danych — na wsi numer domu jest adresem.

    Odrzucenie takich punktów wycięłoby 30% rejestru.
    """
    bez_ulicy = [p for p in _punkty(tmp_path) if p.building == "7"]

    assert len(bez_ulicy) == 1
    assert bez_ulicy[0].street is None
    assert bez_ulicy[0].city == "Chyrzyno"


def test_point_without_coordinates_is_skipped(tmp_path) -> None:
    """Punkt bez georeferencji nie ma po co trafiać do bazy.

    Wstawienie go dałoby wiersz, który nigdy nie trafi w żadne zapytanie,
    a przy okazji zawyżyłby raportowaną liczbę wczytanych punktów.
    """
    assert [p.building for p in _punkty(tmp_path)] == ["43", "7"]


def test_missing_locality_reference_drops_the_point(tmp_path) -> None:
    """Bez miejscowości nie da się zbudować klucza dopasowania."""
    osierocony = FRAGMENT.replace(
        '<prgad:miejscowosc xlink:href="#M1"/>\n      <prgad:ulica2',
        '<prgad:miejscowosc xlink:href="#BRAK"/>\n      <prgad:ulica2',
    )

    assert [p.building for p in _punkty(tmp_path, osierocony)] == ["7"]


def test_empty_file_yields_nothing(tmp_path) -> None:
    pusty = (
        '<?xml version="1.0"?><gml:FeatureCollection xmlns:gml="http://www.opengis.net/gml/3.2"/>'
    )

    assert _punkty(tmp_path, pusty) == []
