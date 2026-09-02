from __future__ import annotations

import math
import random
from copy import deepcopy

import pandas as pd

from .models import StudyConfig, StudySample, SampleType


def _stratified_blocks(
    samples: list[StudySample],
    block_size: int,
    rng: random.Random,
) -> list[list[StudySample]]:
    """
    Distribute samples into QC-interval blocks so that biological groups are
    balanced across each block. Samples within each block are then shuffled.

    Uses round-robin assignment: samples from each group are interleaved across
    blocks so no single block is dominated by one group.
    """
    n_blocks = math.ceil(len(samples) / block_size)

    # Bucket by group
    groups: dict[str, list[StudySample]] = {}
    for s in samples:
        groups.setdefault(s.group or "__ungrouped__", []).append(s)

    # Shuffle within each group before distribution
    for g in groups.values():
        rng.shuffle(g)

    # Round-robin across blocks
    blocks: list[list[StudySample]] = [[] for _ in range(n_blocks)]
    for group_samples in groups.values():
        for i, sample in enumerate(group_samples):
            blocks[i % n_blocks].append(sample)

    # Shuffle within each block so group order within a block is random
    for block in blocks:
        rng.shuffle(block)

    return blocks


def generate_run_sequence(config: StudyConfig) -> pd.DataFrame:
    """
    Build the full injection sequence.

    Structure per batch:
      [blank] [qc_at_start × QC]
        [block_1 samples] [QC]
        [block_2 samples] [QC]
        ...
        [last block samples]
      [qc_at_end × QC] [blank]

    With stratify_by_group=True, each block is balanced across biological groups
    so that signal drift cannot systematically bias one group over another.
    Multi-batch studies get independent opening/closing QC blocks per batch.
    """
    rng = random.Random(config.randomize_seed)
    samples = deepcopy(config.samples)

    # Split into batches
    batches: dict[int, list[StudySample]] = {}
    for s in samples:
        batches.setdefault(s.batch, []).append(s)

    sequence: list[dict] = []

    def add(name: str, sample_type: SampleType, batch: int = 0, group: str = "", notes: str = "") -> None:
        sequence.append({"name": name, "type": sample_type.value, "batch": batch, "group": group, "notes": notes})

    def add_qc(n: int = 1, batch: int = 0) -> None:
        for _ in range(n):
            add("QC", SampleType.QC, batch=batch)

    def add_blank(batch: int = 0) -> None:
        add("Blank", SampleType.BLANK, batch=batch)
        if config.wash_after_blank:
            add("Wash", SampleType.WASH, batch=batch)

    for batch_id in sorted(batches.keys()):
        batch_samples = batches[batch_id]

        # Opening for this batch
        if config.blank_at_start:
            add_blank(batch=batch_id)
        add_qc(config.qc_at_start, batch=batch_id)

        # Build blocks
        use_stratify = (
            config.stratify_by_group
            and config.randomize_samples
            and any(s.group for s in batch_samples)
        )

        if use_stratify:
            blocks = _stratified_blocks(batch_samples, config.qc_frequency, rng)
        else:
            if config.randomize_samples:
                rng.shuffle(batch_samples)
            blocks = [
                batch_samples[i : i + config.qc_frequency]
                for i in range(0, len(batch_samples), config.qc_frequency)
            ]

        for i, block in enumerate(blocks):
            for s in block:
                add(s.name, s.sample_type, batch=s.batch, group=s.group, notes=s.notes)
            # QC after every block except the last (closing QCs cover that)
            if i < len(blocks) - 1:
                add_qc(1, batch=batch_id)

        # Closing for this batch
        add_qc(config.qc_at_end, batch=batch_id)
        if config.blank_at_end:
            add_blank(batch=batch_id)

    df = pd.DataFrame(sequence)
    df.index = pd.RangeIndex(start=1, stop=len(df) + 1, step=1)
    df.index.name = "injection"
    return df


def sequence_summary(df: pd.DataFrame) -> dict:
    counts = df["type"].value_counts().to_dict()
    return {
        "total_injections": len(df),
        "samples": counts.get("Sample", 0),
        "qcs": counts.get("QC", 0),
        "blanks": counts.get("Blank", 0),
        "washes": counts.get("Wash", 0),
        "standards": counts.get("Standard", 0),
    }
