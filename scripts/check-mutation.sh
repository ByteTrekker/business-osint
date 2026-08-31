#!/usr/bin/env bash
# Bramka testów mutacyjnych dla warstwy domenowej.
#
# Zamiast progu procentowego używamy jawnej listy mutantów równoważnych
# (tests/mutation-allowlist.txt). Próg procentowy pozwala nowej luce ukryć się
# w marginesie; lista wymaga nazwania i uzasadnienia każdego wyjątku.
set -euo pipefail

cd "$(dirname "$0")/../backend"

ALLOWLIST="tests/mutation-allowlist.txt"
MUTMUT="${MUTMUT_BIN:-mutmut}"

rm -rf mutants
# Wyjście trzymamy w pliku zamiast wyrzucać do /dev/null. Zagłuszona awaria
# uruchomienia wygląda dokładnie jak przebieg bez ocalałych mutantów, a wtedy
# bramka przepuszcza wszystko — tak było przez cztery zmiany z rzędu, kiedy
# test jednostkowy zaczął ciągnąć moduł spoza piaskownicy mutmut.
run_log="$(mktemp)"
trap 'rm -f "$run_log"' EXIT
PYTHONPATH=src "$MUTMUT" run >"$run_log" 2>&1 || true

survivors="$("$MUTMUT" results 2>/dev/null | grep -E ': survived$' | sed 's/: survived$//' | tr -d ' ' | sort || true)"
allowed="$(grep -vE '^\s*(#|$)' "$ALLOWLIST" | tr -d ' ' | sort)"

unexpected="$(comm -23 <(echo "$survivors") <(echo "$allowed"))"
stale="$(comm -13 <(echo "$survivors") <(echo "$allowed"))"

# `mutmut results` wypisuje wyłącznie ocalałych — liczby ogółem bierzemy ze statystyk.
"$MUTMUT" export-cicd-stats >/dev/null 2>&1 || true
stats="mutants/mutmut-cicd-stats.json"
if [[ -f "$stats" ]]; then
    read -r total killed survived no_tests score <<<"$(python3 -c "
import json
d = json.load(open('$stats'))
total, killed = d['total'], d['killed']
print(total, killed, d['survived'], d['no_tests'],
      f'{killed / total:.1%}' if total else 'n/d')
")"
    echo "Mutanty: ${total}, zabite: ${killed} (${score}), ocalałe: ${survived}, bez testu: ${no_tests}"

    # `no_tests` to mutant, którego nie dotknął żaden test — czyli linia
    # w warstwie domenowej bez pokrycia. Nie pojawia się na liście ocalałych,
    # więc bez tego warunku przechodzi niezauważony. Reguła projektu jest
    # jednoznaczna: nowa reguła domenowa bez testu nie wchodzi.
    if [[ "$no_tests" -gt 0 ]]; then
        echo
        echo "BŁĄD: ${no_tests} mutantów nie dotknął żaden test — to linie"
        echo "w domain/ bez pokrycia. Nie trafiają na listę ocalałych, więc"
        echo "przechodziłyby niezauważone."
        exit 1
    fi

    # Zero zabitych przy niezerowej liczbie mutantów nie znaczy „testy są słabe",
    # tylko „testy się nie uruchomiły". Bez tego warunku bramka jest ślepa na
    # własną awarię: `mutmut results` nie wypisuje wtedy nikogo, więc lista
    # nieuzasadnionych ocalałych wychodzi pusta i skrypt kończy się sukcesem.
    if [[ "$total" -gt 0 && "$killed" -eq 0 ]]; then
        echo
        echo "BŁĄD: żaden mutant nie został zabity — to awaria uruchomienia,"
        echo "a nie wynik. Ostatnie linie z przebiegu mutmut:"
        tail -20 "$run_log" | sed 's/^/      /'
        exit 1
    fi
else
    echo
    echo "BŁĄD: mutmut nie zapisał statystyk — przebieg się nie powiódł."
    tail -20 "$run_log" | sed 's/^/      /'
    exit 1
fi
echo "Dopuszczone jako równoważne: $(echo "$allowed" | grep -c .)"

if [[ -n "$stale" ]]; then
    echo
    echo "UWAGA: te mutanty są na liście dopuszczonych, ale zostały zabite."
    echo "Usuń je z ${ALLOWLIST} — lista ma odzwierciedlać stan faktyczny:"
    echo "$stale" | sed 's/^/      /'
fi

if [[ -n "$unexpected" ]]; then
    echo
    echo "BŁĄD: mutanty przeżyły bez uzasadnienia — brakuje testu:"
    echo "$unexpected" | sed 's/^/      /'
    echo
    echo "Obejrzyj konkretną zmianę:  cd backend && mutmut show <nazwa>"
    echo "Napisz test, który ją wykrywa. Jeżeli mutant jest równoważny"
    echo "(nie istnieje wejście dające inny wynik), dopisz go do ${ALLOWLIST}"
    echo "razem z uzasadnieniem."
    exit 1
fi

echo "Wszystkie ocalałe mutanty są udokumentowane jako równoważne."
