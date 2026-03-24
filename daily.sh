#!/bin/bash
# FVFactory Daily Video Production
# Generates 2 videos: 1 stoicism + 1 self-improvement
# Run: ./daily.sh

cd "$(dirname "$0")"

echo "========================================"
echo "  FVFactory Daily Production"
echo "  $(date '+%Y-%m-%d %H:%M')"
echo "========================================"

# Video 1: Stoicism (Bill - confident elderly man)
echo ""
echo "[1/2] Generating stoicism video..."
python main.py --auto --niche stoicism --voice bill --subtitle-style bold_impact --no-sfx --upload
STATUS1=$?

# Video 2: Self-improvement (Bill voice)
echo ""
echo "[2/2] Generating self-improvement video..."
python main.py --auto --niche self-improvement --voice bill --subtitle-style bold_impact --no-sfx --upload
STATUS2=$?

echo ""
echo "========================================"
echo "  Daily production complete!"
echo "  Video 1 (stoicism): $([ $STATUS1 -eq 0 ] && echo 'OK' || echo 'FAILED')"
echo "  Video 2 (self-improvement): $([ $STATUS2 -eq 0 ] && echo 'OK' || echo 'FAILED')"
echo "  Output: output/"
echo "========================================"
