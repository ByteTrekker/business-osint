# Prawo i ryzyko

Ten dokument nie jest poradą prawną. Jest listą ryzyk, które w tym konkretnym
projekcie są **techniczne w skutkach** — wpływają na model danych i na to, co
trzeba zbudować przed startem, a nie po nim.

## Dlaczego to jest w repozytorium technicznym

Bo trzy z poniższych wymagań przekładają się wprost na tabele i endpointy.
Dopisanie ich po fakcie oznacza migrację danych i utratę historii.

## RODO — publikowanie danych osobowych z rejestrów

Publikujecie imiona, nazwiska i powiązania osób fizycznych, w formie
**ułatwiającej profilowanie** (graf robi dokładnie to, czego pojedynczy odpis
nie robi). To, że dane pochodzą z jawnego rejestru, **nie zwalnia** z obowiązków
administratora danych.

| obowiązek | konsekwencja techniczna | status |
|---|---|---|
| art. 14 — informacja o źródle | provenance przy każdej relacji | ✅ zaimplementowane |
| art. 16 — sprostowanie | korekta jako osobny fakt, bez nadpisywania źródła | ✅ model gotowy |
| art. 17 — usunięcie | możliwość ukrycia encji bez kasowania historii | ⬜ do zrobienia |
| art. 21 — sprzeciw | rejestr żądań + procedura rozpatrzenia | ⬜ do zrobienia |
| art. 15 — dostęp | eksport wszystkiego, co mamy o osobie | ⬜ do zrobienia |

**Uwaga o art. 17:** prawo do usunięcia nie jest bezwzględne — dane z rejestrów
publicznych przetwarzane w prawnie uzasadnionym interesie (art. 6 ust. 1 lit. f)
mogą pozostać. Ale **procedura rozpatrzenia żądania musi istnieć**, a decyzja
musi być udokumentowana. Technicznie: flaga `entities.suppressed_at` + powód,
plus filtr w API — dane zostają dla audytu, znikają z publicznego widoku.

## Ryzyko reputacyjne: fałszywe powiązanie

Największe ryzyko tego produktu nie jest prawne, tylko takie: **błędne scalenie
dwóch osób o tym samym nazwisku tworzy powiązanie, które nie istnieje.**
Jeżeli ktoś na tej podstawie odrzuci kontrahenta albo dziennikarz opublikuje
tekst — to jest realna szkoda.

Dlatego w kodzie:

* zgodność imienia i nazwiska **nigdy** nie daje automatycznego scalenia
  (`domain/identity.py`, test `test_identical_names_alone_never_auto_merge_people`),
* każde scalenie jest zapisane w `entity_merges` i **odwracalne**,
* relacje wyprowadzone przez nas (`shares_person_with`, `shares_address_with`)
  mają `confidence` niższe niż rejestrowe i są **domyślnie ukryte** w API,
* interfejs pokazuje źródło każdej relacji — użytkownik może zweryfikować.

## Dane osobowe wrażliwe

* **PESEL nigdy nie jest zapisywany jawnie** — tylko `blake2b` z pepperem
  z sekretów (`domain/normalization.pesel_hash`). Przestrzeń PESEL jest mała
  i w całości przeliczalna, więc sam hash bez pepperu nie chroni.
* Adresy zamieszkania osób fizycznych — nie pobieramy. Adresy siedzib spółek tak.
  W przypadku jednoosobowych działalności te dwa bywają tym samym adresem;
  to jest przypadek do świadomej decyzji, nie do przeoczenia.
* Daty urodzenia — tylko rocznik, i tylko jeśli jest potrzebny do rozróżnienia
  imienników.

## Warunki korzystania z API rejestrów

* API KRS nie ma opublikowanego regulaminu rate limitu, co **nie znaczy**, że
  można pobierać bez ograniczeń. Zablokowany adres IP zatrzymuje cały projekt.
* `User-Agent` z adresem kontaktowym — jeżeli obciążacie cudzą infrastrukturę,
  dajcie się namierzyć.
* Nie scrapujemy komercyjnych agregatorów. Ryzyko prawne i uzależnienie od
  cudzego produktu.

## Minimum przed publicznym startem

1. Polityka prywatności z podstawą prawną i danymi administratora.
2. Formularz sprostowania/sprzeciwu + rejestr żądań z terminami.
3. Flaga `suppressed_at` i filtr w API.
4. Wyraźna informacja przy każdej relacji: źródło + data pobrania.
5. Zastrzeżenie, że dane pochodzą z rejestrów i mogą być nieaktualne.
