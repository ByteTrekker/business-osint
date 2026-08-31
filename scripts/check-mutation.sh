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
PYTHONPATH=src "$MUTMUT" run >/dev/null 2>&1 || true

survivors="$("$MUTMUT" results 2>/dev/null | grep -E ': survived$' | sed 's/: survived$//' | tr -d ' ' | sort || true)"
allowed="$(grep -vE '^\s*(#|$)' "$ALLOWLIST" | tr -d ' ' | sort)"

unexpected="$(comm -23 <(echo "$survivors") <(echo "$allowed"))"
stale="$(comm -13 <(echo "$survivors") <(echo "$allowed"))"

# `mutmut results` wypisuje wyłącznie ocalałych — liczby ogółem bierzemy ze statystyk.
"$MUTMUT" export-cicd-stats >/dev/null 2>&1 || true
stats="mutants/mutmut-cicd-stats.json"
if [[ -f "$stats" ]]; then
    read -r total killed score <<<"$(python3 -c "
import json
d = json.load(open('$stats'))
total, killed = d['total'], d['killed']
print(total, killed, f'{killed / total:.1%}' if total else 'n/d')
")"
    echo "Mutanty: ${total}, zabite: ${killed} (${score}), ocalałe: $((total - killed))"
else
    echo "Brak statystyk mutmut — sprawdzam wyłącznie listę ocalałych."
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
