"""Training pipeline scaffold for Maverick RL fine-tuning.

Karpathy: "the only piece that earns ML complexity" is the
trajectory donation flywheel + a learned what-to-keep gate +
process-reward training. This package is where that work lands.

Layout:

  __init__.py     (this file)
  schema.py       Klear-AgentForge-compatible trajectory schema
  ingest.py       Read donated trajectories from outbox + dedup + label
  prm_train.py    Train an AgentPRM head from labeled trajectories
                  (arxiv:2511.08325 protocol).
  rlaif.py        RLAIF / DPO loop on the proposer using verifier
                  rewards as the signal.

Status (May 2026): SCHEMA + INGEST scaffolded; PRM_TRAIN + RLAIF are
placeholders that document the next step. Real training requires GPU
+ trajectory volume which is operator-side work, not in-kernel.
"""

__all__ = ["schema", "ingest"]
