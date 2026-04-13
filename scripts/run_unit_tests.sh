#!/usr/bin/env bash
# Поднимает тестовый PostgreSQL (docker-compose.test.yml), затем backend + tool-manager unit-тесты.
# По умолчанию контейнер БД останавливается после прогона; --keep-db оставляет его запущенным.
#
#   ./scripts/run_unit_tests.sh
#   ./scripts/run_unit_tests.sh --keep-db
#   ./scripts/run_unit_tests.sh -- -k test_foo
#
# URL БД по умолчанию совпадает с backend/tests/conftest.py (порт 5433).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="docker-compose.test.yml"
# Хост-порт 5433 из docker-compose.test.yml
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://wifiaudit:wifiaudit@127.0.0.1:5433/wifiaudit_test}"

KEEP_DB=false
PYTEST_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-db)
      KEEP_DB=true
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage: run_unit_tests.sh [--keep-db] [-- pytest-args...]

  --keep-db   Do not stop db-test container on exit
  --          Pass remaining args to pytest (both backend and tool-manager)

Environment:
  TEST_DATABASE_URL  Override Postgres URL (default: ...@127.0.0.1:5433/wifiaudit_test)

Requires: Docker with compose plugin, Python venvs under backend/.venv and tool-manager/.venv
EOF
      exit 0
      ;;
    --)
      shift
      PYTEST_ARGS+=("$@")
      break
      ;;
    *)
      PYTEST_ARGS+=("$1")
      shift
      ;;
  esac
done

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is required" >&2
  exit 1
fi

cleanup() {
  if [[ "$KEEP_DB" == "false" ]]; then
    docker compose -f "$COMPOSE_FILE" down
  fi
}
trap cleanup EXIT

docker compose -f "$COMPOSE_FILE" up -d --wait

backend_py() {
  if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
    "$ROOT/backend/.venv/bin/python" "$@"
  else
    echo "backend/.venv not found. Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-test.txt" >&2
    exit 1
  fi
}

toolmgr_py() {
  if [[ -x "$ROOT/tool-manager/.venv/bin/python" ]]; then
    "$ROOT/tool-manager/.venv/bin/python" "$@"
  else
    echo "tool-manager/.venv not found. Run: cd tool-manager && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-test.txt" >&2
    exit 1
  fi
}

DEFAULT_ARGS=(tests/unit -v)
if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
  PYTEST_ARGS=("${DEFAULT_ARGS[@]}")
fi

echo "==> backend unit tests"
(
  cd "$ROOT/backend"
  backend_py -m pytest "${PYTEST_ARGS[@]}"
)

echo "==> tool-manager unit tests"
(
  cd "$ROOT/tool-manager"
  toolmgr_py -m pytest "${PYTEST_ARGS[@]}"
)

echo "OK"
