# Prompt Series 01 — Learn the App at a High Level (Front + Back)

> **Purpose:** Send these prompts to Claude in order, one at a time.  
> Each prompt builds on the previous response.  
> At the end Claude will produce a single system-knowledge document using the `system.md` template.

---

## Prompt 1 — Project Structure & Repository Layout

```
I'm going to walk you through our codebase so you can build a complete mental model of it.
Let's start with the big picture.

Here is the top-level folder tree of the project (paste the output of `tree /F /A` or `find . -maxdepth 3`):

[PASTE FOLDER TREE HERE]

From this structure, please identify:
1. Is this a monorepo, polyrepo, or monolith?
2. Which folders belong to the frontend, backend, shared libraries, infra/devops?
3. What are the main entry-point files you can see?
4. List every service/app you can identify, one per line, with a one-sentence guess at its responsibility.

Do not summarize broadly — be specific about folder names and file names.
```

---

## Prompt 2 — Backend (Python) Deep Dive

```
Now let's go deep on the Python backend.

Here is the contents of the backend folder (paste relevant files: main entry point, router/routes file, models, config):

Please extract and list:

1. **Framework & version** — e.g. FastAPI 0.110, Flask 3.x, Django 5.x
2. **Entry point** — exact file and the line where the app/server is created
3. **Port** — what port does the server bind to?
4. **All HTTP endpoints** — for each: method, path, handler function name, short description
5. **Database** — what DB engine is used, what is the DB name, what ORM/driver?
6. **All data models / DB tables** — entity name, key fields, field types
7. **Background tasks / workers / scheduled jobs** — if any, list them
8. **Key environment variables read by the app**
9. **External services called** (HTTP clients, SDKs, message brokers)
10. **Auth mechanism** — how are requests authenticated?

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 3 — Frontend (React) Deep Dive

```
Now let's go deep on the React frontend.

Here are the relevant frontend files (paste package.json, main entry, router config, and the top-level component tree or pages folder):

Please extract and list:

1. **Framework & key libraries** — React version, state management (Redux / Zustand / Context), routing library, UI component library, HTTP client
2. **Entry point** — exact file
3. **Dev server port** — what port does `npm run dev` / `vite` / CRA bind to?
4. **All pages / routes** — route path, component name, short description of what the page does
5. **All major shared components** — component name, props it accepts, what it renders
6. **All API calls made to the backend** — for each: HTTP method, URL/path, when it is triggered, what data it sends/receives
7. **State management** — what global state exists? List store slices / contexts and what they hold
8. **Auth flow** — how does the frontend handle login, token storage, and protected routes?
9. **Key constants / feature flags** — any config values, toggle flags, or environment variables consumed by the front end

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 4 — Communication Map (Front ↔ Back ↔ External)

```
Now let's map every communication channel in the system.

Based on what you've learned so far, please produce two tables:

**Table A — Synchronous calls (HTTP REST / WebSocket / gRPC)**
| Source | Target | Protocol | Method + Path | Auth header/token | What triggers it | What it returns |
|--------|--------|----------|---------------|-------------------|-----------------|----------------|

**Table B — Asynchronous / event-driven (queues, Kafka, WebSockets from server, polling)**
| Producer | Consumer | Broker / mechanism | Topic / event name | Message payload schema | When emitted |
|----------|----------|--------------------|--------------------|------------------------|--------------|

Also answer:
- Are there any internal service-to-service calls that bypass the public API?
- Are there any third-party webhooks inbound to the backend?
- Are there any long-polling or SSE (Server-Sent Events) streams?

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 5 — Key Business Flows

```
Now describe the three to five most important end-to-end user flows in the application.

For each flow, write it in this format:

### Flow: [Name]
```
[Step 1] User action → UI component triggered
[Step 2] Frontend → HTTP POST /api/... { payload }
[Step 3] Backend handler → validates, calls DB / external service
[Step 4] Backend → returns response
[Step 5] UI updates state → component re-renders
```
Side effects: [list any DB writes, events emitted, emails sent, etc.]

Focus especially on:
- The dataset/image upload flow
- The label propagation flow
- The model training flow (the "Train Model" button)
- Any flywheel or active-learning loop

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 6 — Infrastructure, DevOps & Auth

```
Finally, let's capture infra and security details.

Please answer each question with the exact value found in config files, docker-compose, Kubernetes manifests, .env.example, or CI files — not guesses.

1. **Containerization** — Docker Compose file name(s)? Service names defined in compose? Which services have health checks?
2. **CI/CD** — What CI system (GitHub Actions, GitLab CI, Jenkins)? Workflow file paths? What does the pipeline do on merge to main?
3. **Environments** — What named environments exist (local, staging, prod)? How are they differentiated (env vars, config files)?
4. **Auth** — JWT? Session cookies? API keys? Exact header name used (e.g. `Authorization: Bearer ...`)?
5. **CORS** — What origins are allowed?
6. **Secrets** — How are secrets injected (dotenv, Vault, AWS Secrets Manager)?
7. **Observability** — Any logging library, log format, metrics endpoint, tracing setup?
8. **Database migrations** — How are migrations run? What tool (Alembic, Flyway, raw SQL)?

If anything is unclear, mark it with [UNCLEAR].
```

---

## Final Prompt — Produce the System Knowledge Document

```
You now have a complete understanding of the system.

After your analysis, produce a **single Markdown document** structured exactly as the `system.md` template below.
Be thorough. If something is unclear, mark it with `[UNCLEAR]` rather than guessing.
Do NOT summarize broadly — go deep. I need specifics: exact service names, exact endpoint paths, exact port numbers, exact field names.

Use this template exactly:

---

# system.md — [PROJECT NAME] System Knowledge Base
> Last updated: [DATE]
> Generated from: [repo URL or folder path]

## 1. Project Overview
## 2. Repository Structure
## 3. Services Inventory
## 4. Communication Map
   ### 4.1 Synchronous (HTTP REST / gRPC / GraphQL)
   ### 4.2 Asynchronous (Events / Queues)
## 5. Domain Entities & Ownership
## 6. External Dependencies
## 7. Auth & Security
## 8. Infrastructure & DevOps
## 9. Key Business Flows
## 10. Architecture Risks & Notes
## 11. Conventions & Standards
## 12. Glossary

---

Fill every section completely based on what you have learned in Prompts 1–6.
```
