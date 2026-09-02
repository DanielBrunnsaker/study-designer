# Study Designer

A chat-first Streamlit app for planning metabolomics MS study run sequences (samples, QCs, blanks, batching) using either structured inputs, or unstructured inputs via a local LLM ([Ollama](https://ollama.com)). 

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ollama

The app talks to a local Ollama server at `http://localhost:11434` and needs a model that supports tool calling.

```bash
# install Ollama: https://ollama.com/download
ollama serve          # if not already running
ollama pull qwen2.5    # or another tool-calling capable model
```

## Run

```bash
streamlit run app.py
```

Then open the URL Streamlit prints (usually http://localhost:8501) and pick your pulled model from the app.
