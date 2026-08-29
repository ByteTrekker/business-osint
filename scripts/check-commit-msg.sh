#!/usr/bin/env bash
# Hook commit-msg: sprawdza pierwszy wiersz komunikatu przed utworzeniem commita.
set -euo pipefail
subject="$(head -n1 "$1")"
exec "$(dirname "$0")/check-commits.sh" --subject "$subject"
