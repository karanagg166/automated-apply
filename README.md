# Job Pulse Agent (`job-pulse-agent`)

An AI-powered job discovery, recruiter contact enrichment, and personalized cold outreach platform designed with strict Human-in-the-Loop (HITL) safety, zero-surprise cost management, and modular architecture.

---

## 🌟 Core Features

- **Automated Multi-Source Discovery:** Gmail job alerts, public ATS boards, direct company postings, and manual URLs.
- **Explainable Matching Engine:** Multi-factor scoring against your resume, preferred titles, tech stack, and locations.
- **5-Stage Contact Enrichment Waterfall:**
  1. *Local Database Cache* (domain patterns, previously discovered recruiters)
  2. *Authorized Public Search* (careers pages, public hiring announcements)
  3. *Pattern Candidate Generation* (`first.last@company.com`, labeled strictly as `candidate`)
  4. *Multi-Provider Enrichment* (Hunter, Apollo, etc. with quota awareness)
  5. *High-Priority Fallback* (SignalHire adapter)
- **Credit & Budget Manager:** Concurrency-safe quota tracking, negative lookup caching, and per-provider cost caps.
- **Human-in-the-Loop Outreach:** Generates targeted Gmail drafts with resume attachments; **never** sends without explicit manual confirmation.
- **FastMCP Tool Layer:** Standards-compliant Model Context Protocol server exposing tool endpoints for AI orchestrators.

---

## 🏗️ Architecture Overview

```text
                    USER
                     │
                     ▼
             NEXT.JS FRONTEND (Phase 4)
            Dashboard + AI Chat
                     │
                     ▼
               BACKEND API
            FastAPI + FastMCP (Phase 1)
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
   AI ORCHESTRATOR          TASK SCHEDULER
   (Tool Calling)         (Discovery Workers)
         │                       │
         └───────────┬───────────┘
                     ▼
              MCP TOOL LAYER
    ┌────────────────┬────────────────┐
    ▼                ▼                ▼
JOB DISCOVERY   ENRICHMENT       GMAIL AGENT
(Feeds/Alerts)  (Waterfall)      (Drafts/Auth)
    │                │                │
    └────────────────┼────────────────┘
                     ▼
               SERVICE LAYER
                     │
                     ▼
           SUPABASE POSTGRESQL
       (Isolated `job_agent` Schema)
```

---

## 🚀 Quickstart (Backend Development)

### Prerequisites

- Python 3.11+
- Git
- Access to Supabase PostgreSQL instance (dedicated `job_agent` schema)

### 1. Environment Setup

```bash
# Create virtual environment
python3.11 -m venv backend/venv

# Activate virtual environment
source backend/venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
```

### 2. Configuration

Copy the example environment file and configure your credentials:

```bash
cp backend/.env.example backend/.env
```

### 3. Run Test Suite

```bash
pytest backend/tests -v
```

### 4. Start Development Server

```bash
uvicorn backend.app.main:app --reload --port 8000
```

---

## 📚 Project Documentation

- [Architecture & System Design](docs/architecture.md)
- [Architectural Decision Records (ADRs)](docs/decisions.md)
- [Implementation Roadmap & Progress](docs/roadmap.md)
- [Phase 1 Implementation Plan](docs/plans/2026-10-14-phase-1-backend-foundation.md)

---

## 🛡️ Non-Negotiable Safety Principles

1. **Account Protection:** No browser automation on authenticated personal sessions, no session cookie harvesting.
2. **Strict HITL:** The system prepares drafts and normalizes data autonomously. Emails are sent **only** after explicit human confirmation.
3. **Cost-First Budgeting:** Cached data is reused first, free tiers are prioritized, and external API calls fail safe when budgets are reached.
4. **Database Isolation:** All application tables reside in the `job_agent` schema, completely segregated from other projects and existing public tables.
