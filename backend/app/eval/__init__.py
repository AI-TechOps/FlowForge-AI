"""Evaluation harness (Phase 5).

`scoring` is deterministic and model-free; `judge` is the rubric model. They
are separate modules on purpose — the deterministic half must stay testable
without a model, and the numbers you can argue about precisely should not
depend on the ones you cannot.
"""
