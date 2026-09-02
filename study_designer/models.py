from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class SampleType(str, Enum):
    SAMPLE = "Sample"
    QC = "QC"
    BLANK = "Blank"
    STANDARD = "Standard"
    WASH = "Wash"


@dataclass
class StudySample:
    name: str
    sample_type: SampleType
    batch: int = 1
    group: str = ""
    notes: str = ""


@dataclass
class StudyConfig:
    samples: list[StudySample] = field(default_factory=list)

    # QC settings
    qc_frequency: int = 5          # inject one QC every N samples
    qc_at_start: int = 3           # QCs before first sample
    qc_at_end: int = 1             # QCs after last sample

    # Blank settings
    blank_at_start: bool = True
    blank_at_end: bool = True
    blank_frequency: int = 0       # 0 = no periodic blanks

    # Wash settings
    wash_after_blank: bool = True

    # Randomization
    randomize_samples: bool = True
    randomize_seed: Optional[int] = None
    block_by_batch: bool = True
    # Stratify samples by biological group across QC blocks to guard against drift
    stratify_by_group: bool = True
