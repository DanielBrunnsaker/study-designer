"""Metabolomics Study Designer — chat-first Streamlit app."""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from study_designer import llm
from study_designer.export import make_excel_report
from study_designer.run_order import sequence_summary
from study_designer.tools import TOOL_DEFINITIONS, execute_tool

st.set_page_config(
    page_title="Metabolomics Study Designer",
    page_icon="🧪",
    layout="wide",
)

# ── session state ─────────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "sample_rows" not in st.session_state:
    st.session_state.sample_rows = pd.DataFrame(columns=["name", "group", "batch", "notes"])
if "run_config" not in st.session_state:
    st.session_state.run_config = {}
if "sequence_df" not in st.session_state:
    st.session_state.sequence_df = None
if "last_explanation" not in st.session_state:
    st.session_state.last_explanation = ""
if "last_upload" not in st.session_state:
    st.session_state.last_upload = None


def build_api_messages(history: list[dict]) -> list[dict]:
    result = []
    for m in history:
        role = m["role"]
        if role == "user":
            result.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            msg: dict = {"role": "assistant", "content": m.get("content", "")}
            if m.get("tool_calls"):
                msg["tool_calls"] = m["tool_calls"]
            result.append(msg)
        elif role == "tool":
            result.append({"role": "tool", "content": m["content"]})
    return result


TYPE_COLORS = {
    "Sample": "#4C78A8",
    "QC": "#F58518",
    "Blank": "#54A24B",
    "Wash": "#B279A2",
    "Standard": "#E45756",
}


def render_sequence_panel(seq_df: pd.DataFrame) -> None:
    s = sequence_summary(seq_df)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", s["total_injections"])
    c2.metric("Samples", s["samples"])
    c3.metric("QCs", s["qcs"])
    c4.metric("Blanks", s["blanks"])
    c5.metric("Washes", s["washes"])

    plot_df = seq_df.reset_index().copy()
    has_groups = plot_df[plot_df["type"] == "Sample"]["group"].astype(bool).any()

    if has_groups:
        view = st.radio(
            "View", ["By type", "By group (swimlane)"],
            horizontal=True, label_visibility="collapsed",
        )
    else:
        view = "By type"

    if view == "By type":
        # Shape encodes biological group; color encodes injection type
        plot_df["symbol_key"] = plot_df.apply(
            lambda r: r["group"] if (r["type"] == "Sample" and r["group"]) else r["type"],
            axis=1,
        )
        fig = px.scatter(
            plot_df,
            x="injection",
            y="type",
            color="type",
            symbol="symbol_key",
            color_discrete_map=TYPE_COLORS,
            hover_data={"name": True, "batch": True, "group": True, "symbol_key": False},
            height=250,
        )
        fig.update_traces(marker_size=10)
        fig.update_layout(showlegend=True, legend_title="Type / Group")

    else:
        # Swimlane: each group on its own row, QC/Blank/Wash on fixed rows
        unique_groups = sorted(
            plot_df[plot_df["type"] == "Sample"]["group"].dropna().unique()
        )
        palette = px.colors.qualitative.D3
        group_colors = {g: palette[i % len(palette)] for i, g in enumerate(unique_groups)}
        color_map = {**TYPE_COLORS, **group_colors}

        plot_df["row"] = plot_df.apply(
            lambda r: r["group"] if (r["type"] == "Sample" and r["group"]) else r["type"],
            axis=1,
        )
        # Y-axis order: groups first (alphabetical), then QC / Blank / Wash
        row_order = unique_groups + ["QC", "Blank", "Wash", "Standard"]

        n_rows = plot_df["row"].nunique()
        height = max(280, n_rows * 55)

        fig = px.scatter(
            plot_df,
            x="injection",
            y="row",
            color="row",
            color_discrete_map=color_map,
            hover_data={"name": True, "batch": True, "type": True},
            category_orders={"row": row_order},
            height=height,
        )
        fig.update_traces(marker_size=10)
        fig.update_layout(showlegend=True, legend_title="Group / Type")

    fig.update_layout(
        yaxis_title="",
        xaxis_title="Injection #",
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Full table", expanded=False):
        st.dataframe(seq_df, use_container_width=True, height=300)

    explanation = st.session_state.last_explanation
    run_config = st.session_state.run_config

    if explanation and run_config:
        excel_bytes = make_excel_report(seq_df, explanation, run_config)
        st.download_button(
            "Download Excel report",
            data=excel_bytes,
            file_name="study_design.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        import io
        buf = io.StringIO()
        seq_df.to_csv(buf)
        st.download_button("Download CSV", buf.getvalue(), "run_sequence.csv", "text/csv")


# ── header ────────────────────────────────────────────────────────────────────
h1, h2 = st.columns([5, 1])
with h1:
    st.title("🧪 Metabolomics Study Designer")
with h2:
    models = llm.list_models()
    if models:
        selected_model = st.selectbox("Model", models, label_visibility="collapsed")
    else:
        selected_model = "qwen3.5:9b"
        st.caption("⚠ Ollama offline")

# ── sequence viewer (full width, collapsible) ─────────────────────────────────
with st.expander("Run sequence", expanded=st.session_state.sequence_df is not None):
    if st.session_state.sequence_df is None:
        st.info("Paste or upload your sample list in the chat to generate a run sequence.")
    else:
        render_sequence_panel(st.session_state.sequence_df)

st.divider()

# ── chat (full width) ─────────────────────────────────────────────────────────
if True:
    uploaded_file = st.file_uploader(
        "Upload sample list (CSV or plain text)",
        type=["csv", "txt"],
        label_visibility="collapsed",
    )

    for msg in st.session_state.chat_history:
        role = msg["role"]
        if role == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif role == "assistant" and not msg.get("tool_calls") and msg.get("content"):
            with st.chat_message("assistant"):
                if msg.get("thinking"):
                    with st.expander("💭 Reasoning", expanded=False):
                        st.markdown(msg["thinking"])
                st.markdown(msg["content"])
        elif role == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc["function"]["name"]
                args = tc["function"].get("arguments", {})
                if fn == "set_samples" and isinstance(args, dict):
                    label = f"🔧 `set_samples` — {len(args.get('samples', []))} samples"
                elif fn == "configure_run":
                    label = "🔧 `configure_run`"
                elif fn == "generate_sequence":
                    label = "🔧 `generate_sequence`"
                else:
                    label = f"🔧 `{fn}`"
                with st.expander(label, expanded=False):
                    st.json(args)
        elif role == "tool":
            with st.expander(f"↩ `{msg.get('tool_name', 'tool')}` result", expanded=False):
                st.caption(msg["content"])

    prompt = st.chat_input("Paste your sample list or describe your study…")

    if uploaded_file and uploaded_file.name != st.session_state.last_upload:
        st.session_state.last_upload = uploaded_file.name
        content = uploaded_file.read().decode("utf-8", errors="replace")
        prompt = f"Here is my sample list ({uploaded_file.name}):\n\n```\n{content}\n```"

    if st.session_state.chat_history:
        if st.button("Clear", type="secondary"):
            st.session_state.chat_history = []
            st.session_state.sample_rows = pd.DataFrame(columns=["name", "group", "batch", "notes"])
            st.session_state.run_config = {}
            st.session_state.sequence_df = None
            st.session_state.last_explanation = ""
            st.session_state.last_upload = None
            st.rerun()

    if prompt:
        if not llm.is_available():
            st.error("Ollama is not running — start it with `ollama serve`.")
        else:
            st.session_state.chat_history.append({"role": "user", "content": prompt})

            state = {
                "sample_rows": st.session_state.sample_rows.copy(),
                "run_config": dict(st.session_state.run_config),
                "sequence_df": st.session_state.sequence_df,
            }

            with st.status("Thinking…", expanded=True) as status:
              try:
                for _ in range(6):
                    api_msgs = build_api_messages(st.session_state.chat_history)
                    response = llm.chat_with_tools(
                        api_msgs, model=selected_model, tools=TOOL_DEFINITIONS
                    )

                    thinking = response.get("thinking", "")
                    if thinking:
                        st.markdown(thinking)

                    tool_calls = response.get("tool_calls")
                    if not tool_calls:
                        final_text = response.get("content", "").strip()
                        if not final_text:
                            final_text = (
                                "*(No explanation returned by the model. "
                                "See the run sequence panel on the right.)*"
                            )
                        st.session_state.chat_history.append(
                            {"role": "assistant", "content": final_text, "thinking": thinking}
                        )
                        if state["sequence_df"] is not None:
                            st.session_state.last_explanation = final_text
                        status.update(label="Done", state="complete", expanded=False)
                        break

                    st.session_state.chat_history.append(
                        {
                            "role": "assistant",
                            "content": response.get("content", ""),
                            "thinking": thinking,
                            "tool_calls": tool_calls,
                        }
                    )

                    for tc in tool_calls:
                        fn_name = tc["function"]["name"]
                        fn_args = tc["function"].get("arguments", {})
                        if isinstance(fn_args, str):
                            try:
                                fn_args = json.loads(fn_args)
                            except json.JSONDecodeError:
                                fn_args = {}
                        try:
                            result, state = execute_tool(fn_name, fn_args, state)
                        except Exception as e:
                            result = f"Error in {fn_name}: {e}"

                        st.session_state.chat_history.append(
                            {"role": "tool", "tool_name": fn_name, "content": result}
                        )

              except Exception as e:
                err = str(e)
                status.update(label="Error", state="error", expanded=False)
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": f"**Error communicating with Ollama:**\n\n```\n{err}\n```"}
                )

            st.session_state.sample_rows = state["sample_rows"]
            st.session_state.run_config = state["run_config"]
            st.session_state.sequence_df = state["sequence_df"]
            st.rerun()
