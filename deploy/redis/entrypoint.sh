#!/bin/sh
set -eu

mode="${REDIS_AOF_RECOVERY:-repair}"
manifest="/data/appendonlydir/appendonly.aof.manifest"
legacy_aof="/data/appendonly.aof"
target=""
check_log="/tmp/redis-check-aof.log"

case "$mode" in
  off|repair|discard) ;;
  *)
    echo "redis-aof-recover: invalid REDIS_AOF_RECOVERY=$mode; use off, repair, or discard" >&2
    exit 64
    ;;
esac

if [ -f "$manifest" ]; then
  target="$manifest"
elif [ -f "$legacy_aof" ]; then
  target="$legacy_aof"
fi

if [ "$mode" = "off" ] || [ -z "$target" ]; then
  exec /usr/local/bin/docker-entrypoint.sh "$@"
fi

if redis-check-aof "$target" >"$check_log" 2>&1; then
  exec /usr/local/bin/docker-entrypoint.sh "$@"
fi

echo "redis-aof-recover: AOF check failed for $target" >&2
cat "$check_log" >&2 || true
pre_repair_backup="/data/recovery-pre-repair/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$pre_repair_backup"
if [ "$target" = "$manifest" ]; then
  cp -a /data/appendonlydir "$pre_repair_backup/"
else
  cp -a "$legacy_aof" "$pre_repair_backup/"
fi
echo "redis-aof-recover: copied persistence files to $pre_repair_backup before repair" >&2
echo "redis-aof-recover: attempting redis-check-aof --fix" >&2

if yes y | redis-check-aof --fix "$target"; then
  echo "redis-aof-recover: AOF repair succeeded" >&2
  exec /usr/local/bin/docker-entrypoint.sh "$@"
fi

echo "redis-aof-recover: AOF repair failed" >&2

if [ "$mode" != "discard" ]; then
  echo "redis-aof-recover: refusing to discard Redis data; set REDIS_AOF_RECOVERY=discard to start with empty state" >&2
  exit 1
fi

backup="/data/recovery-discarded/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup"

[ -d /data/appendonlydir ] && mv /data/appendonlydir "$backup/"
[ -f "$legacy_aof" ] && mv "$legacy_aof" "$backup/"
[ -f /data/dump.rdb ] && mv /data/dump.rdb "$backup/"

echo "redis-aof-recover: moved Redis persistence files to $backup; starting with empty state" >&2
exec /usr/local/bin/docker-entrypoint.sh "$@"
