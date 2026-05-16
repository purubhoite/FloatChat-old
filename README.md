# 🌊 FloatChat — AI-Powered Indian Ocean ARGO Explorer

> **Smart India Hackathon (SIH) Project** | Built for **INCOIS** (Indian National Centre for Ocean Information Services)

FloatChat is an AI-powered conversational interface for exploring Indian Ocean **ARGO float** and **Biogeochemical (BGC)** oceanographic data. Users can ask natural language questions about ocean conditions and receive SQL-backed data visualizations, interactive maps, and scientifically sound explanations — all powered by LLM agents.

---

## ✨ Features

- **Natural Language Querying** — Ask questions like *"Show salinity profiles near the Equator"* or *"Plot deep oxygen trends in the Arabian Sea"*
- **NL-to-SQL Agent** — Converts natural language to SQL queries against an ARGO/BGC database with automatic error repair
- **Intent Classification** — Routes knowledge-based questions to a RAG knowledge base and data queries to the SQL pipeline
- **Interactive Map** — Leaflet-based map showing float locations, trajectories, and profile markers
- **Dynamic Visualizations** — Auto-generates profile plots, time series, T-S diagrams, section plots, and more via Plotly
- **NetCDF Upload** — Upload `.nc` files directly for instant data extraction and visualization
- **Voice Input** — Speech-to-text support for hands-free querying
- **Conversation Context** — Multi-turn conversations with memory for follow-up questions
- **RAG Knowledge Base** — Vector-store-backed retrieval for oceanographic domain knowledge
- **CSV Export** — Download query results as CSV files

---

## 🏗️ Architecture

```
┌─────────────────────────────────┐
│         Dash Frontend           │
│   (app.py + Leaflet Map +      │
│    Plotly Charts + Chat UI)     │
└──────────────┬──────────────────┘
               │ HTTP (REST)
┌──────────────▼──────────────────┐
│       FastAPI Backend           │
│   ┌─────────────────────────┐   │
│   │    Intent Classifier    │   │
│   └──────┬──────────┬───────┘   │
│          │          │           │
│   ┌──────▼───┐ ┌────▼────────┐  │
│   │ NL2SQL   │ │ Knowledge   │  │
│   │ Agent    │ │ Base (RAG)  │  │
│   └──────┬───┘ └─────────────┘  │
│          │                      │
│   ┌──────▼──────────────────┐   │
│   │  SQL Guard + Executor   │   │
│   └──────┬──────────────────┘   │
│          │                      │
│   ┌──────▼──────────────────┐   │
│   │  LLM Explanation Layer  │   │
│   └─────────────────────────┘   │
└─────────────────────────────────┘
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) (for local LLM) **or** a Google Gemini API key
- SQLite database with ARGO/BGC data

### Installation

```bash
# Clone the repository
git clone https://github.com/purubhoite/FloatChat.git
cd FloatChat

# Install dependencies
pip install -r requirements.txt  # if available, else install manually:
# pip install fastapi uvicorn dash dash-leaflet plotly pandas xarray requests python-dotenv chromadb sentence-transformers google-generativeai

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Configuration

Create a `.env` file in the project root:

```env
# LLM Backend: "gemini" or "local_ollama"
LLM_BACKEND="gemini"

# Gemini (if using Gemini)
GEMINI_API_KEY=your_gemini_api_key_here

# Ollama (if using local LLM)
OLLAMA_MODEL="llama3:instruct"
OLLAMA_URL="http://localhost:11434/api/generate"

# Embedding Backend
EMBED_BACKEND="local"
LOCAL_EMBED_MODEL="all-MiniLM-L6-v2"
```

### Running

**Option 1: Using the startup script (Windows)**
```bash
run_all.bat
```

**Option 2: Manual startup**
```bash
# Terminal 1 — Start Backend
uvicorn backend.api:app --reload --port 8000

# Terminal 2 — Start Frontend
python frontend/app.py
```

Then open **http://127.0.0.1:8050** in your browser.

---

## 📁 Project Structure

```
├── backend/
│   ├── api.py                 # FastAPI endpoints (/ask, /upload_nc)
│   ├── ai_pipeline.py         # Main AI orchestration pipeline
│   ├── nl2sql_agent.py        # Natural language to SQL conversion
│   ├── intent_classifier.py   # Query intent classification
│   ├── knowledge_base.py      # RAG-based knowledge retrieval
│   ├── date_rewriter.py       # Date/time expression parsing
│   ├── llm.py                 # LLM abstraction (Gemini/Ollama)
│   ├── mcp_tools.py           # Data tools (describe, schema, viz intent)
│   ├── rag_index.py           # Vector store indexing
│   ├── sql_guard.py           # SQL validation & safe execution
│   ├── embeddings.py          # Embedding model interface
│   ├── schema_docs.py         # Database schema documentation
│   ├── db.py                  # Database connection
│   ├── config.py              # Configuration loader
│   ├── ingest_bgc.py          # BGC data ingestion pipeline
│   └── ingest_core.py         # Core ARGO data ingestion
├── frontend/
│   ├── app.py                 # Dash application (UI + callbacks)
│   └── assets/
│       ├── style.css          # Application styles
│       └── clientside.js      # Client-side JavaScript
├── vector_store/              # ChromaDB vector store for RAG
├── download_bgc_fast_5yr.py   # BGC data download script
├── download_core_fast_5yr.py  # Core ARGO data download script
├── run_all.bat                # Windows startup script
├── .env                       # Environment variables (not tracked)
└── .gitignore
```

---

## 🔬 Tech Stack

| Component | Technology |
|-----------|-----------|
| **Frontend** | Dash (Plotly), Dash-Leaflet |
| **Backend** | FastAPI, Uvicorn |
| **LLM** | Google Gemini / Ollama (Llama 3) |
| **Embeddings** | Sentence-Transformers (all-MiniLM-L6-v2) |
| **Vector Store** | ChromaDB |
| **Database** | SQLite |
| **Data Format** | NetCDF, xarray |
| **Visualization** | Plotly, Leaflet.js |

---

## 📊 Data Sources

- **ARGO Float Data** — Core oceanographic profiles (temperature, salinity, pressure)
- **BGC-ARGO Data** — Biogeochemical parameters (dissolved oxygen, chlorophyll-a, nitrate, pH)
- Source: [Argo Data](https://argo.ucsd.edu/) via INCOIS

---

## 🏆 Smart India Hackathon

This project was developed as part of the **Smart India Hackathon (SIH)** for the problem statement provided by **INCOIS** (Indian National Centre for Ocean Information Services), Government of India.

**Problem**: Build an AI-powered tool to make ARGO and BGC oceanographic data accessible to non-technical decision-makers through natural language interaction.

---

## 👥 Team

Developed by **Team SeaQuery_08**.

---

## 📝 License

This project is for educational and research purposes, developed under the Smart India Hackathon initiative.
