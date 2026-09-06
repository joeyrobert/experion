#!/bin/zsh
# usage: sts_battery.sh [binary] [ms-per-position]
BIN=${1:-bin/experion_v2}
MS=${2:-300}
total=0; solved=0
for i in $(seq 1 15); do
  r=$(timeout 200 $BIN epdtest suites/STS$i.epd $MS 2>/dev/null | tail -1)
  s=$(echo "$r" | grep -oE 'solved [0-9]+' | grep -oE '[0-9]+')
  n=$(echo "$r" | grep -oE '/[0-9]+' | tr -d '/')
  total=$((total + n)); solved=$((solved + s))
  printf "STS%-2d %s\n" $i "$r"
done
echo "TOTAL: $solved/$total"
