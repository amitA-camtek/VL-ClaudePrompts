# system.md — [PROJECT NAME] System Knowledge Base
> Last updated: [DATE]
> Generated from: [repo URL or folder path]

---

## 1. Project Overview
- **Type:** `[monorepo / polyrepo / monolith / microservices / serverless]`
- **Primary language(s):** `[e.g. TypeScript, Python, Go]`
- **Primary framework(s):** `[e.g. NestJS, FastAPI, Gin]`
- **Short description:** [1–3 sentences describing what the system does and for whom]

---

## 2. Repository Structure
```
[paste top-level folder tree here]
```

---

## 3. Services Inventory

### [service-name]
- **Type:** `[API / Worker / Frontend / BFF / Gateway / Cron / Library]`
- **Language & Framework:** `[e.g. Node.js / Express 4.x]`
- **Responsibility:** [What business capability does this service own?]
- **Entry point:** `[e.g. src/main.ts]`
- **Port:** `[e.g. 3001]`
- **Database/Storage:** `[e.g. PostgreSQL — db name: orders_db]`
- **Key env vars:**
  - `DATABASE_URL` — PostgreSQL connection string
  - `JWT_SECRET` — secret for verifying tokens
- **Start command:** `[e.g. npm run start:dev]`

> _(Copy this block for every service in the system)_

---

## 4. Communication Map

### 4.1 Synchronous (HTTP REST / gRPC / GraphQL)
| Source | Target | Protocol | Endpoint / Method | Auth | Description |
|--------|--------|----------|--------------------|------|-------------|
| `api-gateway` | `user-service` | REST | `GET /internal/users/:id` | Service token | Fetch user profile |
| `order-service` | `payment-service` | REST | `POST /payments/charge` | JWT | Initiate charge |

### 4.2 Asynchronous (Events / Queues)
| Producer | Consumer(s) | Broker | Topic / Queue | Message Schema | Description |
|----------|-------------|--------|---------------|----------------|-------------|
| `order-service` | `payment-service`, `notification-service` | Kafka | `order.created` | `{ orderId, userId, amount, items[] }` | Emitted when order is placed |
| `payment-service` | `order-service`, `notification-service` | Kafka | `payment.completed` | `{ orderId, status, transactionId }` | Emitted on payment result |

---

## 5. Domain Entities & Ownership
| Entity | Owner Service | Storage | Key Fields |
|--------|--------------|---------|------------|
| `User` | `user-service` | PostgreSQL | `id, email, passwordHash, role, createdAt` |
| `Order` | `order-service` | PostgreSQL | `id, userId, status, totalAmount, createdAt` |
| `Payment` | `payment-service` | PostgreSQL | `id, orderId, status, provider, transactionId` |

---

## 6. External Dependencies
| Name | Type | Used By | Purpose |
|------|------|---------|---------|
| Stripe | Payment gateway | `payment-service` | Card charging |
| SendGrid | Email API | `notification-service` | Transactional emails |
| Auth0 | Identity provider | `api-gateway` | JWT issuance & validation |
| AWS S3 | Object storage | `media-service` | File uploads |

---

## 7. Auth & Security
- **Auth mechanism:** `[e.g. JWT Bearer tokens]`
- **Token format:** `[e.g. RS256 signed JWT, 1h expiry]`
- **Token issuer:** `[e.g. Auth0 tenant: myapp.auth0.com]`
- **Inter-service auth:** `[e.g. shared HMAC secret in X-Service-Token header]`
- **Public endpoints (no auth required):**
  - `POST /auth/login`
  - `POST /auth/register`
  - `GET /health`

---

## 8. Infrastructure & DevOps
- **Container orchestration:** `[e.g. Docker Compose (local), Kubernetes (staging/prod)]`
- **CI/CD:** `[e.g. GitHub Actions — .github/workflows/]`
- **Environments:** `local` | `staging` | `production`
- **Secrets management:** `[e.g. AWS Secrets Manager / HashiCorp Vault / .env files]`
- **Observability:**
  - Logging: `[e.g. Winston → CloudWatch]`
  - Metrics: `[e.g. Prometheus + Grafana]`
  - Tracing: `[e.g. OpenTelemetry → Jaeger]`

---

## 9. Key Business Flows

### Flow: User Places an Order
```
[1] Client → POST /api/orders  { items, userId }
           → api-gateway (validates JWT)

[2] api-gateway → POST /internal/orders  { items, userId }
               → order-service

[3] order-service → writes Order{status:"pending"} to orders_db
                 → publishes Kafka `order.created` { orderId, userId, amount }

[4] payment-service (consumer: order.created)
    → calls Stripe charge API
    → publishes Kafka `payment.completed` { orderId, status:"success" }

[5] order-service (consumer: payment.completed)
    → updates Order{status:"confirmed"}

[6] notification-service (consumer: payment.completed)
    → sends confirmation email via SendGrid
```

> _(Add a section for each major business flow)_

---

## 10. Architecture Risks & Notes
| Risk | Location | Severity | Suggested Fix |
|------|----------|----------|---------------|
| ⚠️ `report-service` reads directly from `order-service` DB | `report-service/src/db.ts:12` | High | Expose a dedicated read API or use read replicas |
| ⚠️ No dead-letter queue on `payment.completed` consumer | `order-service/src/consumers/` | Medium | Add DLQ + alerting |
| ⚠️ Internal endpoints unauthenticated | `user-service/src/routes/internal.ts` | High | Add service-to-service token validation |

---

## 11. Conventions & Standards
- **Naming conventions:**
  - Services: `kebab-case` (e.g. `order-service`)
  - Kafka topics: `{entity}.{event}` (e.g. `order.created`)
  - Env vars: `SCREAMING_SNAKE_CASE`
  - Database tables: `snake_case` plural (e.g. `user_sessions`)
- **Error handling:** `[e.g. All errors return { statusCode, message, errorCode }]`
- **Testing approach:** `[e.g. Jest unit tests, Supertest integration, Playwright e2e]`
- **Branching strategy:** `[e.g. trunk-based / gitflow]`
- **Code style:** `[e.g. ESLint + Prettier, enforced in CI]`

---

## 12. Glossary
| Term | Definition |
|------|------------|
| BFF | Backend For Frontend — an API layer tailored to a specific UI client |
| DLQ | Dead-Letter Queue — where failed messages are sent after max retries |
| [term] | [definition] |
