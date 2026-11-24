for f in *.*; do [ -f "$f" ] || continue; [ "$f" = solve.sh ] && continue; e="${f##*.}"; mkdir -p "$e"; mv "$f" "$e/"; done
