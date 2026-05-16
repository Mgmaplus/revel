#!/usr/bin/env bash
# Builds tests/fixtures/restaurants_sample.csv from the real CSV by selecting
# specific ids that exercise known data-quality cases. Run from repo root.
# Idempotent: rewrites the fixture each time.

set -euo pipefail

SRC="${1:-input/restaurants.csv}"
DEST="${2:-tests/fixtures/restaurants_sample.csv}"

# Selected ids cover:
#  Tier-A duplicates (same place_id, different id):
#    97527 / 108742  Traif / traif (Brooklyn)
#    43717 / 108718  Dirt Candy
#    7788  / 108719 / 108720  Ivan Ramen (3-way)
#    67553 / 108753 / 108754  Merois / The Merois (case + space variants)
#    74275 / 108766  Antoine's Restaurant / Restaurnt (typo'd name)
#  Edge cases:
#    73220 — price_point = 'budget'    (maps → low)
#    3648  — price_point = 'unknown'   (maps → null)
#    108739 — city is null
#    108057 — latitude/longitude null
#    101075 — quoted city "Washington, DC"
#    103302 — UTM-laden URL with percent encoding
#    108768 — empty google_place_id
#    108743 / 108768 — fabricated/too-long place_ids (will fail prefix check)
#  Clean controls:
#    34561 RPM Italian  (unique chain reference)
#    66660 Lazy Betty   (unique singleton)
SELECTED_IDS=(
    97527 108742
    43717 108718
    7788 108719 108720
    67553 108753 108754
    74275 108766
    73220
    3648
    108739
    108057
    101075
    103302
    108768
    108743
    34561
    66660
)

# Header
head -1 "$SRC" > "$DEST"

# Grab rows by exact-id match in the leading column. The CSV has 1072 data
# rows so a per-id grep is plenty fast (and avoids a Python dependency for
# fixture generation).
for id in "${SELECTED_IDS[@]}"; do
    grep -E "^${id}," "$SRC" >> "$DEST" || {
        echo "warning: id $id not found in $SRC" >&2
    }
done

echo "wrote $(wc -l < "$DEST" | tr -d ' ') lines to $DEST"
