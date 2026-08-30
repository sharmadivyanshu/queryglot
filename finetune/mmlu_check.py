"""MMLU regression check: base vs LoRA adapter on an identical slice.

`mlx_lm.evaluate` has no --adapter-path flag, but its module-level `load` is
`mlx_lm.utils.load`, which does. This wrapper injects the adapter via
MMLU_ADAPTER and defers everything else — args, seeding, scoring, output —
to the stock main(), so base and adapter runs differ in exactly one thing.

    .venv-mlx/bin/python finetune/mmlu_check.py --model ... --tasks mmlu ...
    MMLU_ADAPTER=finetune/adapters .venv-mlx/bin/python finetune/mmlu_check.py ...
"""

import functools
import os

import mlx_lm.evaluate as evaluate

if adapter := os.environ.get("MMLU_ADAPTER"):
    evaluate.load = functools.partial(evaluate.load, adapter_path=adapter)
    print(f"[mmlu_check] adapter injected: {adapter}")
else:
    print("[mmlu_check] no adapter — base model")

evaluate.main()
