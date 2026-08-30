#!/bin/zsh
# MMLU regression: base vs both adapters, same slice (57 subtasks x 4 = 228 Qs),
# same seed, 0-shot. ~3 sequential runs.
set -e
cd "$(dirname "$0")/.."
PY=.venv-mlx/bin/python
ARGS=(--model mlx-community/Qwen3-4B-4bit --tasks mmlu --limit 4 --num-shots 0
      --batch-size 8 --chat-template-args '{"enable_thinking": false}')

echo "=== base ==="
$PY finetune/mmlu_check.py $ARGS --output-dir finetune/mmlu/base

echo "=== adapter: with-schema (arm 3) ==="
MMLU_ADAPTER=finetune/adapters $PY finetune/mmlu_check.py $ARGS --output-dir finetune/mmlu/adapters

echo "=== adapter: no-schema (arm 2) ==="
MMLU_ADAPTER=finetune/adapters-noschema $PY finetune/mmlu_check.py $ARGS --output-dir finetune/mmlu/adapters-noschema

echo "=== done ==="
