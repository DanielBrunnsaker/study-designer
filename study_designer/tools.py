from __future__ import annotations

import pandas as pd

from .models import SampleType, StudySample, StudyConfig
from .run_order import generate_run_sequence, sequence_summary

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "set_samples",
            "description": (
                "Register the biological samples for the study. Always call this first. "
                "If the user has multiple biological factors (e.g. treatment + sex), "
                "combine them into a single composite group string per sample "
                "(e.g. 'KO_male', 'WT_female'). Infer batch from plate/day/batch labels; "
                "default batch=1 if not mentioned."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "samples": {
                        "type": "array",
                        "description": "All biological samples extracted from the user's input",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Sample identifier"},
                                "group": {
                                    "type": "string",
                                    "description": (
                                        "Composite biological group label used for stratification. "
                                        "Combine all relevant factors with underscores, e.g. 'treated_male'. "
                                        "Leave empty only if no biological grouping exists."
                                    ),
                                },
                                "batch": {
                                    "type": "integer",
                                    "description": "Analytical batch number (1, 2, 3…). Default 1.",
                                },
                            },
                            "required": ["name"],
                        },
                    }
                },
                "required": ["samples"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "configure_run",
            "description": (
                "Configure QC frequency, blank placement, and randomization. "
                "Call this after set_samples and before generate_sequence. "
                "Always include qc_frequency, qc_at_start, qc_at_end, randomize_samples, "
                "stratify_by_group, and block_by_batch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "qc_frequency": {
                        "type": "integer",
                        "description": (
                            "Inject one pooled QC every N biological samples. "
                            "Use 5 for <30 samples, 8 for 30-60 samples, 10 for >60 samples. "
                            "Must be between 3 and 20."
                        ),
                    },
                    "qc_at_start": {
                        "type": "integer",
                        "description": "QC injections before the first sample. Always set to 3.",
                    },
                    "qc_at_end": {
                        "type": "integer",
                        "description": "QC injections after the last sample. Always set to 1.",
                    },
                    "blank_at_start": {
                        "type": "boolean",
                        "description": "Solvent blank at the start of each batch. Always true.",
                    },
                    "blank_at_end": {
                        "type": "boolean",
                        "description": "Solvent blank at the end of each batch. Always true.",
                    },
                    "blank_frequency": {
                        "type": "integer",
                        "description": (
                            "Periodic blank every N samples to check carry-over. "
                            "Use 0 (none) unless the matrix has known carry-over issues."
                        ),
                    },
                    "wash_after_blank": {
                        "type": "boolean",
                        "description": "Wash injection after each blank. Always true.",
                    },
                    "randomize_samples": {
                        "type": "boolean",
                        "description": "Randomize biological sample order. Always true.",
                    },
                    "stratify_by_group": {
                        "type": "boolean",
                        "description": (
                            "Balance biological groups evenly across QC blocks. "
                            "Set to true whenever group information is present. "
                            "This prevents signal drift from confounding treatment effects."
                        ),
                    },
                    "block_by_batch": {
                        "type": "boolean",
                        "description": (
                            "Keep batches together in the run order (each batch is a contiguous block). "
                            "Set to true whenever multiple batches exist."
                        ),
                    },
                    "randomize_seed": {
                        "type": "integer",
                        "description": "Random seed for reproducibility. Optional.",
                    },
                },
                "required": [
                    "qc_frequency",
                    "qc_at_start",
                    "qc_at_end",
                    "blank_at_start",
                    "blank_at_end",
                    "wash_after_blank",
                    "randomize_samples",
                    "stratify_by_group",
                    "block_by_batch",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_sequence",
            "description": (
                "Generate the full injection run sequence from the current samples and config. "
                "Always call this after configure_run."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# Hard limits applied regardless of what the LLM passes
_QC_FREQ_MIN = 3
_QC_FREQ_MAX = 20
_QC_START_MIN = 1
_QC_END_MIN = 1


def execute_tool(tool_name: str, arguments: dict, state: dict) -> tuple[str, dict]:
    """Execute a tool and return (result_message, updated_state)."""

    if tool_name == "set_samples":
        rows = [
            {
                "name": s.get("name", ""),
                "group": s.get("group", ""),
                "batch": max(1, int(s.get("batch", 1))),
                "notes": "",
            }
            for s in arguments.get("samples", [])
        ]
        state["sample_rows"] = pd.DataFrame(rows)
        groups = sorted({r["group"] for r in rows if r["group"]})
        batches = sorted({r["batch"] for r in rows})
        parts = [f"Registered {len(rows)} samples."]
        if groups:
            parts.append(f"Groups: {', '.join(groups)}.")
        if len(batches) > 1:
            parts.append(f"Batches: {', '.join(str(b) for b in batches)}.")
        return " ".join(parts), state

    elif tool_name == "configure_run":
        cfg = {**state.get("run_config", {}), **arguments}
        # Clamp to safe ranges
        cfg["qc_frequency"] = max(_QC_FREQ_MIN, min(_QC_FREQ_MAX, int(cfg.get("qc_frequency", 5))))
        cfg["qc_at_start"] = max(_QC_START_MIN, int(cfg.get("qc_at_start", 3)))
        cfg["qc_at_end"] = max(_QC_END_MIN, int(cfg.get("qc_at_end", 1)))
        state["run_config"] = cfg
        return (
            f"Config set: QC every {cfg['qc_frequency']} samples, "
            f"{cfg['qc_at_start']} opening QCs, {cfg['qc_at_end']} closing QCs, "
            f"stratify={cfg.get('stratify_by_group', True)}, "
            f"block_by_batch={cfg.get('block_by_batch', True)}."
        ), state

    elif tool_name == "generate_sequence":
        df = state.get("sample_rows", pd.DataFrame())
        if df.empty:
            return "No samples registered yet. Call set_samples first.", state
        cfg = state.get("run_config", {})
        samples = [
            StudySample(
                name=str(r["name"]),
                sample_type=SampleType.SAMPLE,
                batch=int(r.get("batch", 1)),
                group=str(r.get("group", "")),
            )
            for _, r in df.iterrows()
        ]
        config = StudyConfig(
            samples=samples,
            qc_frequency=cfg.get("qc_frequency", 5),
            qc_at_start=cfg.get("qc_at_start", 3),
            qc_at_end=cfg.get("qc_at_end", 1),
            blank_at_start=cfg.get("blank_at_start", True),
            blank_at_end=cfg.get("blank_at_end", True),
            blank_frequency=cfg.get("blank_frequency", 0),
            wash_after_blank=cfg.get("wash_after_blank", True),
            randomize_samples=cfg.get("randomize_samples", True),
            randomize_seed=cfg.get("randomize_seed"),
            block_by_batch=cfg.get("block_by_batch", True),
            stratify_by_group=cfg.get("stratify_by_group", True),
        )
        seq_df = generate_run_sequence(config)
        s = sequence_summary(seq_df)
        state["sequence_df"] = seq_df
        return (
            f"Sequence generated: {s['total_injections']} total injections "
            f"({s['samples']} samples, {s['qcs']} QCs, {s['blanks']} blanks, {s['washes']} washes)."
        ), state

    return f"Unknown tool: {tool_name}", state
