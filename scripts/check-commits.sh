#!/usr/bin/env bash
# Waliduje komunikaty commitów i tytuł PR wg Conventional Commits (po angielsku).
# Reguła opisana w CLAUDE.md, sekcja "Git: commity, gałęzie i pull requesty".
#
#   ./scripts/check-commits.sh                  # zakres origin/main..HEAD
#   ./scripts/check-commits.sh main..HEAD       # własny zakres
#   ./scripts/check-commits.sh --subject "feat(api): add endpoint"
set -euo pipefail

TYPES='feat|fix|docs|refactor|test|perf|build|ci|chore|revert'
PATTERN="^(${TYPES})(\([a-z0-9,._/-]+\))?!?: .+"
MAX_SUBJECT=72

failed=0

check_subject() {
    local subject="$1" origin="$2"
    if [[ "$subject" =~ ^Merge\  ]]; then
        return 0
    fi
    if ! printf '%s' "$subject" | grep -qE "$PATTERN"; then
        echo "BŁĄD [${origin}] nie pasuje do Conventional Commits:"
        echo "      ${subject}"
        echo "      oczekiwany format: <type>(<scope>): <subject>, typy: ${TYPES//|/, }"
        failed=1
        return 0
    fi
    if (( ${#subject} > MAX_SUBJECT )); then
        echo "BŁĄD [${origin}] subject ma ${#subject} znaków, limit ${MAX_SUBJECT}:"
        echo "      ${subject}"
        failed=1
        return 0
    fi
    echo "OK   [${origin}] ${subject}"
}

if [[ "${1:-}" == "--subject" ]]; then
    check_subject "${2:?brak treści po --subject}" "tytuł PR"
else
    range="${1:-origin/main..HEAD}"
    if ! git rev-parse "$range" >/dev/null 2>&1; then
        echo "Nie mogę rozwiązać zakresu '${range}'." >&2
        exit 2
    fi
    count=0
    while IFS= read -r subject; do
        [[ -z "$subject" ]] && continue
        count=$((count + 1))
        check_subject "$subject" "commit"
    done < <(git log --no-merges --format=%s "$range")
    if (( count == 0 )); then
        echo "Brak commitów w zakresie ${range} — nic do sprawdzenia."
    fi
fi

exit "$failed"
