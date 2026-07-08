#!/usr/bin/env bash
# One-command new-course cycle for Ochiq Kurs.
#
#   new-course.sh course_<kurs>.py [-o NN_<kurs>_course.sql]          # local stage
#   new-course.sh course_<kurs>.py [-o NN_<kurs>_course.sql] --prod   # ship it
#
# Local: Cyrillic check -> new_course.py emit (slug-keyed SQL) -> apply twice
#   (idempotency) -> DB invariants -> thumbnail (category color from DB) ->
#   render check on a throwaway dev server.
# Prod: fresh backup -> scp + dbshell apply -> prod invariants -> rsync
#   thumbnail -> live-page curls. Same SQL file both sides — no serial ids.
#
# Content (konspekt + test) is a separate step: author konspekt_<kurs>.py
# (v2 slug contract) and run pipeline.sh afterwards.
#
# Env overrides: OCHIQKURS_DB, OCHIQKURS_DB_USER, OCHIQKURS_DB_PASSWORD,
#   OCHIQKURS_VENV_PY, OCHIQKURS_PROD_SSH, OCHIQKURS_SITE.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SKILL_DIR/../../.." && pwd)"
export PGPASSWORD="${OCHIQKURS_DB_PASSWORD:-1234}"
PSQL=(psql -U "${OCHIQKURS_DB_USER:-ochiqkurs_user}" -d "${OCHIQKURS_DB:-ochiqkurs}")
VENV_PY="${OCHIQKURS_VENV_PY:-$HOME/.local/share/virtualenvs/web-site-_VaapEyK/bin/python}"
PROD_SSH="${OCHIQKURS_PROD_SSH:-myserver}"
SITE="${OCHIQKURS_SITE:-https://ochiqkurs.uz}"
PORT=8079
SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-%r@%h-%p" -o ControlPersist=120)
SSH=(ssh "${SSH_OPTS[@]}" "$PROD_SSH")
SCP=(scp -q "${SSH_OPTS[@]}")

DATA="" ; OUT="" ; PROD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prod) PROD=1 ;;
    -o) OUT="$2"; shift ;;
    *) DATA="$1" ;;
  esac
  shift
done
[ -n "$DATA" ] && [ -f "$DATA" ] || { echo "usage: new-course.sh course_x.py [-o out.sql] [--prod]"; exit 2; }
DATA="$(cd "$(dirname "$DATA")" && pwd)/$(basename "$DATA")"
[ -n "$OUT" ] || OUT="${DATA%.py}.sql"

step() { printf '\n== %s\n' "$*"; }

step "Cyrillic check: $(basename "$DATA")"
if grep -n '[а-яА-Я]' "$DATA"; then
  echo "FAIL: Cyrillic look-alikes found (above)"; exit 1
fi
echo "clean"

step "generate SQL -> $OUT"
GEN_OUT=$(python3 "$SKILL_DIR/new_course.py" "$DATA" -o "$OUT")
echo "$GEN_OUT"
SLUG=$(echo "$GEN_OUT" | tail -1)
CREF="(SELECT id FROM learning_course WHERE slug = '$SLUG')"

step "apply locally twice (idempotency)"
"${PSQL[@]}" -q -v ON_ERROR_STOP=1 -f "$OUT"
"${PSQL[@]}" -q -v ON_ERROR_STOP=1 -f "$OUT"
echo "OK+IDEMPOTENT"

VERIFY_SQL="$(mktemp -t verify_newcourse)"
cat > "$VERIFY_SQL" <<EOF
SELECT 'summary|' || count(DISTINCT m.id) || '|' || count(l.id) || '|' ||
  coalesce(sum(l.duration_seconds), 0)
FROM learning_module m JOIN learning_lesson l ON l.module_id = m.id
WHERE m.course_id = $CREF;
SELECT 'empty_desc|' || count(*)
FROM learning_lesson l JOIN learning_module m ON m.id = l.module_id
WHERE m.course_id = $CREF AND l.description = '';
SELECT 'no_video_id|' || count(*)
FROM learning_lesson l JOIN learning_module m ON m.id = l.module_id
WHERE m.course_id = $CREF AND l.lesson_type = 'video' AND l.youtube_video_id = '';
EOF

check_invariants() {  # $1 = labelled psql output
  local out="$1" mods lessons dur
  echo "$out"
  IFS='|' read -r _ mods lessons dur <<< "$(grep '^summary' <<< "$out")"
  [ "${mods:-0}" -gt 0 ] && [ "${lessons:-0}" -gt 0 ] && [ "${dur:-0}" -gt 0 ] \
    || { echo "FAIL: empty course (mods=$mods lessons=$lessons dur=$dur)"; return 1; }
  for bad in empty_desc no_video_id; do
    [ "$(grep "^$bad" <<< "$out" | cut -d'|' -f2)" = "0" ] || { echo "FAIL: $bad != 0"; return 1; }
  done
  echo "invariants OK"
}

step "local invariants ($SLUG)"
check_invariants "$("${PSQL[@]}" -t -A -f "$VERIFY_SQL")"

step "thumbnail"
CAT=$("${PSQL[@]}" -t -A -c "SELECT ct.name || '|' || ct.color FROM learning_course c
  JOIN learning_category ct ON ct.id = c.category_id WHERE c.slug = '$SLUG'")
CAT_NAME=$(cut -d'|' -f1 <<< "$CAT" | tr '[:lower:]' '[:upper:]')
CAT_COLOR=$(cut -d'|' -f2 <<< "$CAT")
C_TITLE=$("${PSQL[@]}" -t -A -c "SELECT title FROM learning_course WHERE slug = '$SLUG'")
THUMB="$REPO_DIR/media/course_thumbnails/$SLUG.png"
"$VENV_PY" "$SKILL_DIR/../course-thumbnail/generate.py" \
  --title "$C_TITLE" --label "$CAT_NAME" --color "$CAT_COLOR" --out "$THUMB"
echo "$THUMB ($CAT_NAME/$CAT_COLOR) — LOOK AT IT (Read tool): title wrap, collisions"

step "render check (dev server :$PORT)"
( cd "$REPO_DIR" && exec "$VENV_PY" manage.py runserver --noreload "$PORT" >/dev/null 2>&1 ) &
SERVER_PID=$!
disown "$SERVER_PID"
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then break; fi
  sleep 0.5
done
FIRST_LESSON=$("${PSQL[@]}" -t -A -c "
  SELECT m.slug || '/' || l.slug || '/' FROM learning_lesson l
  JOIN learning_module m ON m.id = l.module_id
  WHERE m.course_id = $CREF ORDER BY m.\"order\", l.\"order\" LIMIT 1")
RENDER_FAIL=0
for u in "" "$FIRST_LESSON"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/malaka/$SLUG/$u")
  [ "$code" = "200" ] || { echo "BAD $code /malaka/$SLUG/$u"; RENDER_FAIL=1; }
done
kill "$SERVER_PID" 2>/dev/null || true; trap - EXIT
[ "$RENDER_FAIL" = 0 ] || { echo "FAIL: render"; exit 1; }
echo "course + first lesson render 200"

if [ "$PROD" = 0 ]; then
  echo; echo "LOCAL PASS — prod uchun: new-course.sh $DATA -o $OUT --prod"
  echo "keyin kontent: konspekt_<kurs>.py (v2 slug contract) + pipeline.sh"
  exit 0
fi

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

step "prod thumbnail"
rsync -a -e "ssh ${SSH_OPTS[*]}" "$THUMB" "$PROD_SSH:~/opencourse/media/course_thumbnails/"
echo "rsynced"

step "live pages"
LIVE_FAIL=0
for u in "/malaka/$SLUG/" "/malaka/$SLUG/$FIRST_LESSON" "/media/course_thumbnails/$SLUG.png"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$SITE$u")
  [ "$code" = "200" ] || { echo "BAD $code $SITE$u"; LIVE_FAIL=1; }
done
[ "$LIVE_FAIL" = 0 ] || { echo "FAIL: live pages"; exit 1; }
echo "live OK"

echo; echo "PROD PASS ($SLUG) — endi kontent: konspekt_<kurs>.py + pipeline.sh --prod"
