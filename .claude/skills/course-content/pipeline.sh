#!/usr/bin/env bash
# One-command pipeline for a course content module (konspekt_<kurs>.py).
#
# Local stage (always):
#   normalize apostrophes -> Cyrillic look-alike check -> generate SQL via
#   seedlib -> apply locally TWICE (idempotency proof) -> DB invariants ->
#   render every new konspekt/test page on a throwaway dev server.
# Prod stage (--prod):
#   module-id divergence check (local vs prod) -> fresh backup -> scp ->
#   dbshell apply -> prod invariants -> live-page curls -> /tmp cleanup.
#
# Usage: pipeline.sh path/to/konspekt_x.py [-o out.sql] [--prod]
#
# Env overrides: OCHIQKURS_DB, OCHIQKURS_DB_USER, OCHIQKURS_DB_PASSWORD,
#   OCHIQKURS_VENV_PY, OCHIQKURS_PROD_SSH, OCHIQKURS_SITE.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PGPASSWORD="${OCHIQKURS_DB_PASSWORD:-1234}"
PSQL=(psql -U "${OCHIQKURS_DB_USER:-ochiqkurs_user}" -d "${OCHIQKURS_DB:-ochiqkurs}")
VENV_PY="${OCHIQKURS_VENV_PY:-$HOME/.local/share/virtualenvs/web-site-_VaapEyK/bin/python}"
PROD_SSH="${OCHIQKURS_PROD_SSH:-myserver}"
SITE="${OCHIQKURS_SITE:-https://ochiqkurs.uz}"
PORT=8078
# one multiplexed TCP connection for all ssh/scp calls (avoids sshd
# MaxStartups throttling on rapid successive connections)
SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-%r@%h-%p" -o ControlPersist=120)
SSH=(ssh "${SSH_OPTS[@]}" "$PROD_SSH")
SCP=(scp -q "${SSH_OPTS[@]}")

CONTENT="" ; OUT="" ; PROD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prod) PROD=1 ;;
    -o) OUT="$2"; shift ;;
    *) CONTENT="$1" ;;
  esac
  shift
done
[ -n "$CONTENT" ] && [ -f "$CONTENT" ] || { echo "usage: pipeline.sh konspekt_x.py [-o out.sql] [--prod]"; exit 2; }

CONTENT="$(cd "$(dirname "$CONTENT")" && pwd)/$(basename "$CONTENT")"
MOD_DIR="$(dirname "$CONTENT")"
MOD="$(basename "$CONTENT" .py)"
[ -n "$OUT" ] || OUT="$MOD_DIR/${MOD}_content.sql"

step() { printf '\n== %s\n' "$*"; }

step "normalize + Cyrillic check: $MOD.py"
python3 "$SKILL_DIR/normalize.py" "$CONTENT"
if grep -n '[а-яА-Я]' "$CONTENT"; then
  echo "FAIL: Cyrillic look-alikes found (above)"; exit 1
fi

step "generate SQL -> $OUT"
GEN_OUT=$(PYTHONPATH="$SKILL_DIR:$MOD_DIR" python3 - "$MOD" "$OUT" <<'PY'
import importlib, sys
mod = importlib.import_module(sys.argv[1])
from seedlib import emit_course_sql
emit_course_sql(mod, sys.argv[2])
print(mod.COURSE_ID)
PY
)
echo "$GEN_OUT"
COURSE_ID=$(echo "$GEN_OUT" | tail -1)

step "apply locally twice (idempotency)"
"${PSQL[@]}" -q -v ON_ERROR_STOP=1 -f "$OUT"
"${PSQL[@]}" -q -v ON_ERROR_STOP=1 -f "$OUT"
echo "OK+IDEMPOTENT"

VERIFY_SQL="$(mktemp -t verify_course)"
cat > "$VERIFY_SQL" <<EOF
SELECT 'summary|' || count(DISTINCT m.id) || '|' ||
  count(*) FILTER (WHERE l.lesson_type='article') || '|' ||
  count(*) FILTER (WHERE l.lesson_type='quiz')
FROM learning_module m JOIN learning_lesson l ON l.module_id=m.id
WHERE m.course_id = $COURSE_ID;
SELECT 'bad_modules|' || count(*) FROM (
  SELECT m.id FROM learning_module m JOIN learning_lesson l ON l.module_id=m.id
  WHERE m.course_id = $COURSE_ID GROUP BY m.id
  HAVING count(*) FILTER (WHERE l.lesson_type='article') <> 1
      OR count(*) FILTER (WHERE l.lesson_type='quiz') <> 1
      OR (max(l."order") FILTER (WHERE l.lesson_type='article')
        < max(l."order") FILTER (WHERE l.lesson_type='quiz')) IS NOT TRUE
) x;
SELECT 'empty_desc|' || count(*)
FROM learning_lesson l JOIN learning_module m ON m.id=l.module_id
WHERE m.course_id = $COURSE_ID AND l.description = '';
SELECT 'no_correct|' || count(*) FROM learning_quizquestion qq
JOIN learning_quiz q ON q.id=qq.quiz_id
JOIN learning_lesson l ON l.id=q.lesson_id
JOIN learning_module m ON m.id=l.module_id
WHERE m.course_id = $COURSE_ID
AND NOT EXISTS (SELECT 1 FROM learning_quizchoice c
                WHERE c.question_id=qq.id AND c.is_correct);
EOF

check_invariants() {  # $1 = labelled psql output
  local out="$1" mods konspekt test
  echo "$out"
  IFS='|' read -r _ mods konspekt test <<< "$(grep '^summary' <<< "$out")"
  [ "$mods" = "$konspekt" ] && [ "$mods" = "$test" ] || { echo "FAIL: counts mods=$mods konspekt=$konspekt test=$test"; return 1; }
  for bad in bad_modules empty_desc no_correct; do
    [ "$(grep "^$bad" <<< "$out" | cut -d'|' -f2)" = "0" ] || { echo "FAIL: $bad != 0"; return 1; }
  done
  echo "invariants OK"
}

step "local invariants (course $COURSE_ID)"
check_invariants "$("${PSQL[@]}" -t -A -f "$VERIFY_SQL")"

step "render check (dev server :$PORT)"
URLS=$("${PSQL[@]}" -t -A -c "
  SELECT c.slug || '/' || m.slug || '/' || l.slug || '/'
  FROM learning_lesson l
  JOIN learning_module m ON m.id=l.module_id
  JOIN learning_course c ON c.id=m.course_id
  WHERE m.course_id = $COURSE_ID AND l.lesson_type IN ('article','quiz')")
( cd "$SKILL_DIR/../../.." && exec "$VENV_PY" manage.py runserver --noreload "$PORT" >/dev/null 2>&1 ) &
SERVER_PID=$!
disown "$SERVER_PID"
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then break; fi
  sleep 0.5
done
RENDER_FAIL=0
for u in $URLS; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/malaka/$u")
  [ "$code" = "200" ] || { echo "BAD $code /malaka/$u"; RENDER_FAIL=1; }
done
kill "$SERVER_PID" 2>/dev/null || true; trap - EXIT
[ "$RENDER_FAIL" = 0 ] || { echo "FAIL: render"; exit 1; }
echo "$(echo "$URLS" | grep -c .) pages render 200"

if [ "$PROD" = 0 ]; then
  echo; echo "LOCAL PASS — prod uchun: pipeline.sh $CONTENT -o $OUT --prod"
  exit 0
fi

step "module-id divergence check (local vs prod)"
LOCAL_IDS=$("${PSQL[@]}" -t -A -c "SELECT id||':'||slug FROM learning_module WHERE course_id=$COURSE_ID ORDER BY id")
PROD_IDS=$("${SSH[@]}" "cd ~/opencourse && venv/bin/python manage.py dbshell -- -t -A -c \"SELECT id||':'||slug FROM learning_module WHERE course_id=$COURSE_ID ORDER BY id\"")
if [ "$LOCAL_IDS" != "$PROD_IDS" ]; then
  echo "FAIL: module ids diverge — remap by slug before applying (see gen_dl94_prod.py pattern)"
  diff <(echo "$LOCAL_IDS") <(echo "$PROD_IDS") || true
  exit 1
fi
echo "ids match"

step "prod backup"
"${SSH[@]}" 'bash ~/backups/pg_backup.sh && ls -t ~/backups/*.sql.gz | head -1'

step "prod apply"
"${SCP[@]}" "$OUT" "$VERIFY_SQL" "$PROD_SSH:/tmp/"
OUT_BASE=$(basename "$OUT"); VER_BASE=$(basename "$VERIFY_SQL")
"${SSH[@]}" "cd ~/opencourse && venv/bin/python manage.py dbshell -- -q -v ON_ERROR_STOP=1 -f /tmp/$OUT_BASE"
echo "applied"

step "prod invariants"
check_invariants "$("${SSH[@]}" "cd ~/opencourse && venv/bin/python manage.py dbshell -- -t -A -f /tmp/$VER_BASE")"
"${SSH[@]}" "rm -f /tmp/$OUT_BASE /tmp/$VER_BASE" || echo "warn: /tmp cleanup failed (harmless)"

step "live pages"
LIVE_FAIL=0
for u in $URLS; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$SITE/malaka/$u")
  [ "$code" = "200" ] || { echo "BAD $code $SITE/malaka/$u"; LIVE_FAIL=1; }
done
[ "$LIVE_FAIL" = 0 ] || { echo "FAIL: live pages"; exit 1; }
echo "$(echo "$URLS" | grep -c .) live pages 200"

echo; echo "PROD PASS (course $COURSE_ID)"
