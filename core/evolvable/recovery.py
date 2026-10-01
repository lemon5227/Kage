"""Baseline recovery: preserve the existing stop behavior."""

def recover(error, history, checkpoints):
    return {"action": "stop"}
