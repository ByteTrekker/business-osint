"""Normalizacja to fundament entity resolution — testujemy ją najgęściej."""

from __future__ import annotations

import pytest

from business_osint.domain.normalization import (
    TERYT_WOJEWODZTWA,
    address_natural_key,
    address_point_key,
    address_search_key,
    company_name_blocking_key,
    format_address,
    is_valid_krs,
    is_valid_nip,
    is_valid_regon,
    normalize_company_name,
    normalize_person_name,
    person_blocking_key,
    pesel_hash,
    split_person_name,
    street_from_address_line,
    wojewodztwo_z_teryt,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ALFA TECHNOLOGIE Sp. z o.o.", "alfa technologie"),
        ('"ALFA TECHNOLOGIE" SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ', "alfa technologie"),
        ("ALFA TECHNOLOGIE sp. z o.o. w likwidacji", "alfa technologie"),
        ("ALFA  TECHNOLOGIE   S.A.", "alfa technologie"),
        ("Łódzka Fabryka Żarówek Sp.J.", "lodzka fabryka zarowek"),
    ],
)
def test_company_names_collapse_to_same_form(raw: str, expected: str) -> None:
    assert normalize_company_name(raw) == expected


def test_legal_form_variants_produce_identical_blocking_key() -> None:
    variants = [
        "BETA LOGISTYKA Sp. z o.o.",
        "BETA LOGISTYKA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
        "beta logistyka sp.zo.o.",
    ]
    keys = {company_name_blocking_key(v) for v in variants}
    assert len(keys) == 1, f"warianty formy prawnej rozjechały się: {keys}"


def test_normalize_does_not_swallow_meaningful_letters() -> None:
    # "SP" w środku nazwy nie jest formą prawną — nie wolno go wyciąć.
    assert "spawmet" in normalize_company_name("SPAWMET Sp. z o.o.")


def test_person_name_is_diacritic_insensitive() -> None:
    assert normalize_person_name("Michał Wójcik") == "michal wojcik"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jan Kowalski", ("Jan", "Kowalski")),
        ("KOWALSKI, JAN ANDRZEJ", ("JAN ANDRZEJ", "KOWALSKI")),
        ("Jan Andrzej Kowalski", ("Jan Andrzej", "Kowalski")),
    ],
)
def test_split_person_name(raw: str, expected: tuple[str, str]) -> None:
    assert split_person_name(raw) == expected


def test_person_blocking_key_separates_namesakes_by_birth_year() -> None:
    a = person_blocking_key("Jan", "Kowalski", 1975)
    b = person_blocking_key("Jan", "Kowalski", 1990)
    assert a != b


@pytest.mark.parametrize("nip", ["5252445170", "525-244-51-70", "1132456789"])
def test_valid_nip(nip: str) -> None:
    assert is_valid_nip(nip)


@pytest.mark.parametrize("nip", ["5252445172", "1234567890", "525244517", ""])
def test_invalid_nip(nip: str) -> None:
    assert not is_valid_nip(nip)


def test_regon_9_and_14_digits() -> None:
    assert is_valid_regon("012345675")
    assert not is_valid_regon("012345678")


def test_krs_is_format_only() -> None:
    assert is_valid_krs("0000111111")
    assert not is_valid_krs("111111")


def test_pesel_is_never_stored_in_plaintext() -> None:
    digest = pesel_hash("44051401359", pepper="test-pepper")
    assert "44051401359" not in digest
    assert len(digest) == 32
    # Ten sam PESEL + ten sam pepper = ten sam identyfikator (stabilne dopasowanie).
    assert digest == pesel_hash("44051401359", pepper="test-pepper")
    # Inny pepper = inny identyfikator (wyciek bazy nie pozwala na rainbow table).
    assert digest != pesel_hash("44051401359", pepper="other-pepper")


def test_pesel_hash_rejects_malformed_input() -> None:
    with pytest.raises(ValueError, match="11 cyfr"):
        pesel_hash("123", pepper="x")


def test_regon_14_digits_validates_both_parts() -> None:
    """REGON 14-cyfrowy (jednostka lokalna) ma dwie sumy kontrolne — obie muszą się zgadzać."""
    # Poprawny 9-cyfrowy rdzeń, ale błędna cyfra kontrolna części 14-cyfrowej.
    assert not is_valid_regon("01234567500001")
    # Błędny rdzeń dyskwalifikuje cały numer, niezależnie od reszty.
    assert not is_valid_regon("01234567800001")


def test_regon_rejects_other_lengths() -> None:
    assert not is_valid_regon("0123456")
    assert not is_valid_regon("")


def test_single_token_name_is_treated_as_surname() -> None:
    """Rejestry bywają niekompletne — jeden token traktujemy jako nazwisko."""
    assert split_person_name("Kowalski") == ("", "Kowalski")


# --- luki wykryte przez testy mutacyjne (`make mutation`) -------------------


@pytest.mark.parametrize("regon", ["012345675", "274837620"])
def test_valid_9_digit_regon_is_accepted(regon: str) -> None:
    """Numery dobrane tak, by każda waga miała wpływ na wynik.

    Zestaw pochodzi z analizy testów mutacyjnych: numer z zerami na pozycjach
    ważonych nie odróżnia zmiany wagi, bo 0 * w == 0 dla dowolnego w.
    """
    assert is_valid_regon(regon)


@pytest.mark.parametrize("regon", ["01234567500008", "27483762063480", "89889439383283"])
def test_valid_14_digit_regon_is_accepted(regon: str) -> None:
    """Numer jednostki lokalnej: obie sumy kontrolne muszą się zgadzać."""
    assert is_valid_regon(regon)


def test_regon_control_digit_ten_maps_to_zero() -> None:
    """Reszta 10 zapisywana jest jako cyfra kontrolna 0 — stąd podwójne modulo."""
    assert is_valid_regon("274837620")
    assert not is_valid_regon("274837621")


@pytest.mark.parametrize(
    ("value", "checker"),
    [
        ("012-345-675", is_valid_regon),
        ("525-244-51-70", is_valid_nip),
        ("KRS 0000111111", is_valid_krs),
    ],
)
def test_identifiers_ignore_separators(value: str, checker: object) -> None:
    """Rejestry i użytkownicy wklejają numery z myślnikami, spacjami i prefiksem."""
    assert checker(value)  # type: ignore[operator]


def test_all_zero_nip_is_rejected() -> None:
    """0000000000 przechodzi sumę kontrolną, ale nie jest numerem podatnika."""
    assert not is_valid_nip("0000000000")


def test_checksum_rejects_wrong_digit_slice() -> None:
    """Zły wycinek cyfr ma się kończyć wyjątkiem, a nie cichym obcięciem."""
    from business_osint.domain.normalization import _checksum

    with pytest.raises(ValueError, match=r"argument 2 is shorter|zip\(\)"):
        _checksum("1234567890", (6, 5, 7, 2, 3, 4, 5, 6, 7), 11)


def test_company_blocking_key_truncates_at_twelve_characters() -> None:
    """Klucz blokujący ma stałą długość — inaczej długie nazwy tworzą osobne bloki."""
    key = company_name_blocking_key("PRZEDSIĘBIORSTWO WIELOBRANŻOWE BUDOWLANE Sp. z o.o.")
    assert key == "przedsiebior"
    assert len(key) == 12


def test_company_blocking_key_removes_spaces() -> None:
    assert company_name_blocking_key("ALFA TECH Sp. z o.o.") == "alfatech"


def test_person_blocking_key_uses_only_the_first_given_name() -> None:
    """Drugie imię bywa pomijane w rejestrach — nie może różnicować klucza."""
    assert person_blocking_key("Jan Andrzej", "Kowalski") == person_blocking_key("Jan", "Kowalski")
    assert person_blocking_key("Jan Andrzej", "Kowalski") == "jan|kowalski"


def test_person_blocking_key_collapses_compound_surname() -> None:
    assert person_blocking_key("Anna", "Nowak Kowalska") == "anna|nowakkowalska"


def test_person_blocking_key_without_given_name() -> None:
    assert person_blocking_key("", "Kowalski") == "|kowalski"


def test_person_blocking_key_appends_birth_year_only_when_known() -> None:
    assert person_blocking_key("Jan", "Kowalski", 1975) == "jan|kowalski|1975"
    assert person_blocking_key("Jan", "Kowalski", None) == "jan|kowalski"


def test_pesel_hash_ignores_formatting() -> None:
    assert pesel_hash("44051401359", pepper="p") == pesel_hash("440 514 013 59", pepper="p")


def test_pesel_hash_error_message_is_exact() -> None:
    with pytest.raises(ValueError, match=r"^PESEL musi mieć 11 cyfr$"):
        pesel_hash("123", pepper="x")


def test_split_person_name_splits_on_the_first_comma() -> None:
    """Format 'NAZWISKO, IMIONA' — dzielimy na pierwszym przecinku.

    Przy dzieleniu od końca 'KOWALSKI, JAN, ANDRZEJ' dałoby nazwisko
    'KOWALSKI, JAN', czyli sklejenie nazwiska z imieniem.
    """
    assert split_person_name("KOWALSKI, JAN ANDRZEJ") == ("JAN ANDRZEJ", "KOWALSKI")
    assert split_person_name("KOWALSKI, JAN, ANDRZEJ") == ("JAN, ANDRZEJ", "KOWALSKI")


def test_nip_prefix_with_remainder_ten_is_always_rejected() -> None:
    """Reszta 10 nie ma reprezentacji jako cyfra kontrolna.

    Taki prefiks jest odrzucany dla każdej z dziesięciu możliwych cyfr —
    dlatego jawny strażnik `control != 10` był martwym kodem.
    """
    assert not any(is_valid_nip("701001234" + str(digit)) for digit in range(10))


# --- Adres: dwa klucze, dwie role -------------------------------------------


def test_address_search_key_keeps_word_boundaries() -> None:
    """Klucz wyszukiwania musi mieć spacje — indeks pełnotekstowy dzieli po słowach.

    Bez nich cały adres jest jednym tokenem i zapytanie „chemikow plock" nie ma
    czego dopasować. Dokładnie tak wyglądało 2,4 mln adresów w bazie.
    """
    assert address_search_key("Chemików 7, 09-411 Płock") == "chemikow 7 09 411 plock"


def test_address_natural_key_removes_them_on_purpose() -> None:
    """Klucz scalania musi być sklejony, żeby różnice w zapisie zniknęły."""
    assert address_natural_key("ul. Chemików 7, 09-411 Płock") == "ulchemikow709411plock"


def test_the_two_address_keys_are_not_the_same_value() -> None:
    """Jedna wartość w dwóch rolach była właśnie tym defektem.

    Ten test istnieje po to, żeby ktoś nie „uprościł" ich z powrotem do jednej
    funkcji: klucz scalania i pole wyszukiwania mają sprzeczne wymagania.
    """
    adres = "Chemików 7, 09-411 Płock"

    assert address_search_key(adres) != address_natural_key(adres)


def test_differently_punctuated_addresses_merge_to_one_key() -> None:
    """„Chemików 7, 09-411, Płock" i „Chemików 7, 09-411 Płock" to ten sam adres."""
    assert address_natural_key("Chemików 7, 09-411, Płock") == address_natural_key(
        "Chemików 7, 09-411 Płock"
    )


def test_address_without_a_street_still_yields_searchable_words() -> None:
    """Adresy wiejskie to sam numer i miejscowość — muszą być wyszukiwalne tak samo."""
    assert address_search_key("18, 46-310 Jamy") == "18 46 310 jamy"


# --- Klucz dopasowania do punktów adresowych PRG ----------------------------


def test_address_point_key_ignores_case_and_diacritics() -> None:
    """Rejestry zapisują te same nazwy różnie — to nie jest różnica w adresie."""
    assert address_point_key(city="PŁOCK", street="Chemików", building="7") == (
        address_point_key(city="Płock", street="chemikow", building="7")
    )


def test_street_type_prefix_is_dropped() -> None:
    """„ul. Chemików" i „Chemików" to ta sama ulica.

    Polskie rejestry zapisują rodzaj ulicy niekonsekwentnie: „ul.", „ul",
    „aleja" albo wcale. Zostawienie go rozbiłoby dopasowanie na czymś, co nie
    niesie informacji odróżniającej.
    """
    key = address_point_key(city="Płock", street="Chemików", building="7")

    for prefix in ("ul. ", "ul ", "UL. ", "al. ", "Aleja ", "pl. ", "os. "):
        assert address_point_key(city="Płock", street=f"{prefix}Chemików", building="7") == key


def test_building_number_keeps_its_letter_and_slash() -> None:
    """`28a` i `14/2` to część adresu, nie ozdobnik — muszą przetrwać normalizację.

    Sprowadzenie ich do samej cyfry scaliłoby ze sobą różne lokale pod tym
    samym numerem budynku.
    """
    assert address_point_key(city="Gdańsk", street="Leczkowa", building="28a").endswith("28a")
    assert address_point_key(city="Gdańsk", street="Leczkowa", building="28b") != (
        address_point_key(city="Gdańsk", street="Leczkowa", building="28a")
    )


def test_the_three_parts_stay_separated() -> None:
    """Człony są rozdzielone, żeby „Nowa 12" nie zlało się z „Nowa1 2".

    Sklejenie wszystkiego w jeden ciąg — tak jak w kluczu naturalnym adresu —
    tworzyłoby fałszywe trafienia między różnymi adresami.
    """
    assert address_point_key(city="X", street="Nowa", building="12") != (
        address_point_key(city="X", street="Nowa1", building="2")
    )


def test_different_localities_never_share_a_key() -> None:
    """Ta sama ulica i numer w dwóch miastach to dwa różne adresy."""
    assert address_point_key(city="Płock", street="Chemików", building="7") != (
        address_point_key(city="Gdańsk", street="Chemików", building="7")
    )


def test_empty_parts_do_not_break_the_key() -> None:
    """Adres wiejski bywa bez ulicy — klucz ma powstać, a nie wybuchnąć."""
    assert address_point_key(city="Jamy", street="", building="18") == "jamy||18"


def test_flat_number_is_not_glued_to_the_building_number() -> None:
    """`14/2` i `1/42` to różne adresy i muszą mieć różne klucze.

    Usunięcie separatora dawało z obu napis `142`, czyli dwa różne mieszkania
    trafiałyby w ten sam punkt adresowy. Wykryte przez test mutacyjny, nie przez
    pokrycie: linia była wykonywana, tylko żaden test nie sprawdzał jej skutku.
    """
    assert address_point_key(city="X", street="Nowa", building="14/2") != (
        address_point_key(city="X", street="Nowa", building="1/42")
    )


# --- Zapis adresu i rozkład linii adresowej ---------------------------------


def test_address_is_written_the_way_a_person_writes_it() -> None:
    """Przecinek oddziela ulicę od kodu, a nie każdy człon od każdego.

    Wcześniej wychodziło „ul. Kąty, 14, 34-443, Sromowce Wyżne" — poprawne
    maszynowo, ale nikt tak adresu nie zapisuje.
    """
    assert (
        format_address(
            street="ul. Kąty", building="14", unit="2", postal_code="34-443", city="Sromowce Wyżne"
        )
        == "ul. Kąty 14/2, 34-443 Sromowce Wyżne"
    )


def test_flat_is_joined_to_the_building_with_a_slash() -> None:
    assert (
        format_address(street="Nowa", building="1", unit="5", postal_code="", city="") == "Nowa 1/5"
    )


def test_building_without_a_flat_has_no_slash() -> None:
    assert format_address(street="Nowa", building="1", unit="", postal_code="", city="") == "Nowa 1"


def test_flat_without_a_building_is_still_kept() -> None:
    """Rejestr bywa niekompletny; zgubienie numeru lokalu byłoby utratą danych."""
    assert format_address(street="Nowa", building="", unit="5", postal_code="", city="") == "Nowa 5"


def test_rural_address_without_a_street_starts_with_the_number() -> None:
    """Na wsi numer domu **jest** adresem — nie ma z czym go łączyć."""
    assert (
        format_address(street="", building="18", unit="", postal_code="46-310", city="Jamy")
        == "18, 46-310 Jamy"
    )


def test_missing_postal_code_does_not_leave_a_dangling_separator() -> None:
    assert (
        format_address(street="Nowa", building="1", unit="", postal_code="", city="Płock")
        == "Nowa 1, Płock"
    )


def test_completely_empty_address_gives_an_empty_string() -> None:
    assert format_address(street="", building="", unit="", postal_code="", city="") == ""


def test_city_is_removed_from_the_start_of_an_address_line() -> None:
    """GLEIF wpisuje miejscowość do linii adresu; w kolumnie ulicy jej nie chcemy."""
    assert street_from_address_line("PŁOCK BIELSKA 67", city="PŁOCK", building="67") == "BIELSKA"


def test_city_is_matched_regardless_of_case_and_diacritics() -> None:
    assert street_from_address_line("Płock Bielska 67", city="PLOCK", building="67") == "Bielska"


def test_street_type_prefix_is_removed_from_the_line() -> None:
    assert street_from_address_line("ul. Chemików 7", city="Płock", building="7") == "Chemików"


def test_building_number_is_removed_only_from_the_end() -> None:
    """„3 Maja 5" ma zostać „3 Maja" — numer w nazwie ulicy nie jest numerem domu."""
    assert street_from_address_line("3 Maja 5", city="Płock", building="5") == "3 Maja"


def test_number_inside_the_name_is_not_touched() -> None:
    """Numer, który nie stoi na końcu, nie jest numerem budynku."""
    assert street_from_address_line("3 Maja", city="Płock", building="3") == "3 Maja"


def test_line_without_a_number_is_returned_as_the_street() -> None:
    assert street_from_address_line("Bielska", city="Płock", building=None) == "Bielska"


def test_line_that_is_only_the_city_and_number_falls_back_to_the_whole_line() -> None:
    """Lepszy pełny zapis niż pusta ulica — nie zgadujemy, czego nie ma."""
    assert street_from_address_line("PŁOCK 67", city="PŁOCK", building="67") == "PŁOCK 67"


def test_city_appearing_later_in_the_line_is_not_stripped() -> None:
    """Usuwamy miejscowość tylko z początku — inaczej okroilibyśmy nazwę ulicy."""
    assert street_from_address_line("Aleja Płocka 4", city="Płock", building="4") == "Płocka"


def test_comma_after_the_city_is_removed_too() -> None:
    """Część rejestrów oddziela miejscowość przecinkiem — nie ma zostać w ulicy."""
    assert street_from_address_line("PŁOCK, BIELSKA 67", city="PŁOCK", building="67") == "BIELSKA"


def test_building_number_matches_regardless_of_letter_case() -> None:
    """`67A` w linii i `67a` w polu numeru to ten sam numer.

    Rejestry nie uzgadniają wielkości liter w numerach z literą, a bez
    porównania bez względu na wielkość numer zostawałby w nazwie ulicy.
    """
    assert street_from_address_line("Bielska 67A", city="Płock", building="67a") == "Bielska"
    assert street_from_address_line("Bielska 67a", city="Płock", building="67A") == "Bielska"


def test_separator_left_after_the_number_is_removed() -> None:
    """Po odcięciu numeru nie może zostać wiszący ukośnik ani przecinek.

    Zdarza się, że pole numeru niesie sam lokal, a linia ma `budynek/lokal` —
    po usunięciu lokalu zostaje „Bielska 67/", co nie jest nazwą ulicy.
    """
    assert street_from_address_line("Bielska 67/3", city="Płock", building="3") == "Bielska 67"


def test_comma_after_the_city_is_removed_even_without_a_building_number() -> None:
    """Bez numeru budynku nie ma drugiego sprzątania — przecinek musi zniknąć od razu.

    Z numerem różnica jest niewidoczna, bo późniejsze odcięcie numeru czyści
    to samo. Adres bez numeru jest jedynym wejściem, które to rozstrzyga.
    """
    assert street_from_address_line("PŁOCK, BIELSKA", city="PŁOCK", building=None) == "BIELSKA"


def test_street_name_starting_with_x_is_not_truncated() -> None:
    """Sprzątanie po numerze usuwa separatory, nie litery.

    „Xawerego Dunikowskiego" to prawdziwa ulica; zbyt szeroki zestaw znaków
    do obcięcia zjadłby jej pierwszą literę.
    """
    assert street_from_address_line("Xawerego 5", city="Płock", building="5") == "Xawerego"


def test_street_name_starting_with_x_survives_the_city_strip_too() -> None:
    """Po odcięciu miejscowości usuwamy separatory, nie litery.

    Bliźniaczy przypadek do sprzątania po numerze — ta sama pomyłka może
    wejść w każde z dwóch miejsc, więc każde ma własny test.
    """
    assert street_from_address_line("Płock, Xawerego", city="Płock", building=None) == "Xawerego"


# --- Województwo z kodu TERYT -----------------------------------------------


def test_voivodeship_is_read_from_the_teryt_prefix() -> None:
    """Dwie pierwsze cyfry TERYT to urzędowy kod województwa.

    Bez tego dopasowanie punktu adresowego idzie po samej nazwie miejscowości,
    a „Zawada", „Buczków" i „Lubień" istnieją w kilku województwach naraz —
    7 459 adresów dostało w ten sposób współrzędne oddalone o kilkaset kilometrów.
    """
    assert wojewodztwo_z_teryt("0805022") == "lubuskie"
    assert wojewodztwo_z_teryt("1465011") == "mazowieckie"
    assert wojewodztwo_z_teryt("3210011") == "zachodniopomorskie"


def test_every_voivodeship_code_is_known() -> None:
    """Szesnaście województw, szesnaście kodów — brak któregokolwiek to cicha luka.

    Punkt z nieznanym kodem nie dostałby województwa i wypadłby z warunku
    rozstrzygającego dopasowanie.
    """
    assert len(TERYT_WOJEWODZTWA) == 16
    assert all(wojewodztwo_z_teryt(f"{kod}00000") for kod in TERYT_WOJEWODZTWA)


def test_unknown_or_missing_code_gives_none() -> None:
    """Nieznany kod ma dać `None`, a nie zgadywać województwo."""
    assert wojewodztwo_z_teryt("9900000") is None
    assert wojewodztwo_z_teryt(None) is None
    assert wojewodztwo_z_teryt("") is None
    assert wojewodztwo_z_teryt("0") is None


def test_the_bare_voivodeship_code_is_enough() -> None:
    """Dwie cyfry to najkrótsze poprawne wejście — sam kod województwa.

    TERYT gminy ma siedem znaków, ale kod województwa jest jego przedrostkiem
    i bywa podawany osobno. Odrzucenie go byłoby wymaganiem informacji, której
    funkcja nie potrzebuje.
    """
    assert wojewodztwo_z_teryt("08") == "lubuskie"
    assert wojewodztwo_z_teryt("14") == "mazowieckie"


class TestNazwaSpolkiCywilnej:
    """CEIDG nie podaje nazwy spółki — wyłuskujemy ją z nazwy wpisu wspólnika."""

    def test_name_after_the_partner_phrase_is_the_partnership(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        assert nazwa_spolki_z_wpisu("JAROSŁAW TKACZYK wspólnik spółki cywilnej PLASTECH") == (
            "PLASTECH"
        )

    def test_trailing_sc_marker_is_not_part_of_the_name(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        # „PLASTECH S.C." i „PLASTECH" to ta sama spółka; gdyby końcówka
        # zostawała, dwaj wspólnicy nie uzgodniliby jednej nazwy.
        assert nazwa_spolki_z_wpisu("Marek Tkaczyk Wspólnik Spółki Cywilnej PLASTECH S.C.") == (
            "PLASTECH"
        )

    def test_quotes_around_the_name_are_stripped(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        assert nazwa_spolki_z_wpisu('ANDRZEJ STĘPIEŃ - wspólnik spółki cywilnej "MASZ"') == "MASZ"

    def test_longer_phrase_wins_so_the_name_is_not_cut_short(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        # „wspólnikiem spółki cywilnej" zawiera w sobie „spółki cywilnej";
        # dopasowanie krótszego wariantu zostawiłoby wiodące „m".
        assert nazwa_spolki_z_wpisu("JAN KOWALSKI wspólnikiem spółki cywilnej ALFA") == "ALFA"

    def test_name_without_any_hint_yields_nothing(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        # Zgadywanie z „Marek Duda" dałoby etykietę będącą nazwiskiem osoby.
        assert nazwa_spolki_z_wpisu("Marek Duda") is None

    def test_single_character_leftover_is_noise_not_a_name(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        assert nazwa_spolki_z_wpisu("JAN KOWALSKI wspólnik spółki cywilnej X") is None

    def test_partners_agreeing_on_a_name_settle_it(self) -> None:
        from business_osint.domain.normalization import uzgodnij_nazwe_spolki

        assert (
            uzgodnij_nazwe_spolki(
                [
                    "JAROSŁAW TKACZYK wspólnik spółki cywilnej PLASTECH",
                    "Marek Tkaczyk Wspólnik Spółki Cywilnej PLASTECH S.C.",
                ]
            )
            == "PLASTECH"
        )

    def test_the_name_more_partners_give_wins(self) -> None:
        from business_osint.domain.normalization import uzgodnij_nazwe_spolki

        assert (
            uzgodnij_nazwe_spolki(
                [
                    "A wspólnik spółki cywilnej BETA",
                    "B wspólnik spółki cywilnej ALFA",
                    "C wspólnik spółki cywilnej ALFA",
                ]
            )
            == "ALFA"
        )

    def test_partners_without_a_hint_leave_the_partnership_unnamed(self) -> None:
        from business_osint.domain.normalization import uzgodnij_nazwe_spolki

        assert uzgodnij_nazwe_spolki(["Marek Duda", "Karolina Duda"]) is None

    def test_punctuation_right_after_the_phrase_is_not_part_of_the_name(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        # Wpisy bywają zapisane z dwukropkiem albo myślnikiem po zwrocie
        # o wspólniku; bez ich odcięcia nazwa zaczynałaby się od znaku.
        assert nazwa_spolki_z_wpisu("JAN KOWALSKI, wspólnik spółki cywilnej: ALFA") == "ALFA"
        assert nazwa_spolki_z_wpisu("JAN KOWALSKI wspólnik spółki cywilnej — BETA") == "BETA"

    def test_punctuation_exposed_by_removing_the_sc_suffix_is_trimmed(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        # Dopiero usunięcie końcówki „s.c." odsłania myślnik na końcu nazwy —
        # gdyby ostatnie przycięcie nie działało, zostałoby „ALFA -".
        assert nazwa_spolki_z_wpisu("JAN KOWALSKI wspólnik spółki cywilnej ALFA - s.c.") == "ALFA"

    def test_leading_quote_survives_to_the_final_trim(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        assert nazwa_spolki_z_wpisu("JAN KOWALSKI wspólnik spółki cywilnej ALFA, s.c.") == "ALFA"

    def test_the_first_partner_phrase_wins_not_the_last(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        # Nazwa spółki sama bywa zbudowana ze zwrotu o spółce cywilnej.
        # Szukanie od końca zwróciłoby wyłącznie ogon, gubiąc początek nazwy.
        assert (
            nazwa_spolki_z_wpisu("ALFA SPÓŁKA CYWILNA BETA SPÓŁKA CYWILNA GAMMA")
            == "BETA SPÓŁKA CYWILNA GAMMA"
        )

    def test_two_letter_name_is_kept(self) -> None:
        from business_osint.domain.normalization import nazwa_spolki_z_wpisu

        # Granica jest przy dwóch znakach: „AB" to nazwa, „X" to resztka.
        assert nazwa_spolki_z_wpisu("JAN KOWALSKI wspólnik spółki cywilnej AB") == "AB"
