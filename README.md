# MoodJournal — AI-Powered Personal Journal with Sentiment Trends

An intelligent journaling application that classifies your mood automatically and surfaces
emotional patterns over time, without requiring manual tagging or self-scoring.

**Status:** AWS deployment version. `sam validate --lint` and `sam build` both pass, and the test
suite runs offline. The runtime is AWS-only — there is no local server component.

---

## 🎯 Features

- **Free-form journaling** — write naturally, with no structure imposed
- **Automatic mood classification** — Google Gemini classifies each entry on save
- **Mood trends dashboard** — distribution, daily trend line and week-by-week summary
- **AI-written reflections** — on demand, or generated automatically every 7 days
- **Search and filtering** — by text, mood and date range, with pagination
- **Analytics pipeline** — entries exported to S3 and queried through Athena, shown in the
  dashboard's *Long-term Insights* card
- **Custom authentication** — username/password with JWT, verified by a Lambda authorizer

---

## 🏗️ Architecture

```
Browser ── HTTPS ──→ CloudFront ── origin access control ──→ S3 (static frontend)
   │
   └── REST, Bearer JWT ──→ API Gateway ──→ JWT authorizer (Lambda)
                               │
                               ├──→ API handlers (14 Lambda functions, Python 3.14)
                               │       ├──→ DynamoDB (entries, reflections, users)
                               │       ├──→ Google Gemini API (classify mood, write reflection)
                               │       └──→ Athena ──→ S3 analytics bucket
                               │              (dashboard "Long-term Insights" queries)
                               │
                               └──→ Export function ── POST /analytics/export ──┐
                                                                                ├──→ S3 analytics bucket
EventBridge Scheduler ── rate(1 day) ──→ Export function ───────────────────────┘     (JSON Lines)
                      ── rate(7 days) ─→ Scheduled reflection ──→ DynamoDB, Gemini
```

The same export function runs daily for every user and on demand for the signed-in user, when
the dashboard's *Export Latest Entries* button is pressed. Athena reads those exports through a
Glue table; the dashboard's own charts still read DynamoDB directly.

**Diagrams**

- [`docs/architecture/moodjournal-architecture.png`](docs/architecture/moodjournal-architecture.png)
  — Figure 1: every route, Lambda function, table operation and scheduled job
- [`docs/architecture/moodjournal-architecture.html`](docs/architecture/moodjournal-architecture.html)
  — its source, drawn on an HTML canvas; open it in a browser and press **S** to save a PNG

**AWS services**

| Service | Role |
|---|---|
| Lambda | 17 functions: 15 API routes, the JWT authorizer and the weekly reflection job; the export route also runs daily |
| API Gateway | REST API with a request authorizer and CORS |
| DynamoDB | Journal entries, reflections and user accounts |
| S3 | Static frontend hosting, plus the analytics export bucket |
| CloudFront | CDN in front of the frontend bucket, via origin access control |
| Athena + Glue | Named SQL queries over the exported data, shown in the dashboard's *Long-term Insights* card |
| EventBridge Scheduler | Weekly reflections, daily analytics export |
| CloudWatch | Structured JSON logs from every function |

**Third-party:** Google Gemini API, for mood classification and reflection writing.

---

## 📋 Mood Categories

| Mood | Meaning | Score |
|---|---|---|
| `POSITIVE` | Optimistic, happy, accomplished | 2 |
| `NEUTRAL` | Calm, balanced, factual | 1 |
| `ANXIOUS` | Worried, uncertain, stressed | 0 |
| `NEGATIVE` | Sad, frustrated, discouraged | -1 |

Scores exist only to draw the trend chart. They are not a measurement of wellbeing, and the UI
says so.

---

## 📁 Project Structure

```
asm3_MoodJournal/
├── backend/
│   ├── handlers/          # One Lambda entry point per route
│   ├── services/          # Business logic: auth, journal, analytics, reflection, gemini, athena
│   ├── repositories/      # DynamoDB access
│   ├── models/            # Entities and their DynamoDB mapping
│   ├── utils/             # Validation, responses, logging, pagination, passwords
│   ├── requirements.txt       # Lambda runtime dependencies (PyJWT only)
│   └── requirements-dev.txt   # Test and tooling dependencies
│
├── frontend/              # HTML5 / CSS3 / vanilla JS
│   ├── index.html  history.html  dashboard.html
│   ├── reflection.html  login.html  register.html
│   ├── styles.css
│   └── js/
│       ├── config.js      # API base URL — rewritten at deploy time
│       └── common.js      # API client and shared helpers
│
├── infrastructure/
│   ├── template.yaml      # AWS SAM template — the whole stack
│   └── athena/            # Database, table and example queries
│
├── docs/
│   └── architecture/      # Figure 1: architecture diagram (PNG) and its canvas source (HTML)
│
├── scripts/
│   ├── deploy_frontend.ps1   # Config + upload + cache invalidation
│   └── seed_demo_data.py     # Demo account and back-dated entries
│
└── tests/                 # Service and handler tests (no AWS required)
```

---

## 🔧 Setup

### Prerequisites

- **Python 3.14+** — matches the Lambda runtime
- **AWS account** with credentials configured (`aws configure`)
- **AWS SAM CLI**
- **Google Gemini API key** — https://aistudio.google.com/apikey

### Install

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements-dev.txt
```

`backend/requirements.txt` deliberately contains only PyJWT: the Lambda runtime provides boto3,
and bundling it would only inflate the deployment package.

---

## 🧪 Testing

```powershell
pytest
```

The suite covers the service layer and the Lambda handlers using stub repositories and a patched
Gemini, so it needs **no AWS credentials, no DynamoDB table and no API quota**. It runs in about
a second.

Covered: registration and login (including that a wrong password and an unknown username are
indistinguishable), token issuing and rejection of forged tokens, journal CRUD, cross-user
isolation, case-insensitive search, dashboard aggregation against every field the frontend reads,
reflection generation, and that reflections send Gemini only aggregates and titles, never journal
text. Athena is exercised with a fake client: every named query is scoped to the caller and
counts each entry's latest export only, unknown query names never reach Athena, and a slow query
is stopped and returned as a 504 before API Gateway's 29-second limit.

---

## 🔍 Code Quality

```powershell
ruff check .
ruff format .
mypy backend
```

---

## ☁️ Deployment

### 1. Validate and build

```powershell
sam validate --template infrastructure\template.yaml --lint
sam build --template infrastructure\template.yaml
```

If the project lives in a OneDrive folder, `sam build` can fail with `Access is denied` while
deleting `.aws-sam\build`, because OneDrive marks the synced folders read-only. Build outside
OneDrive instead, and point `sam deploy` at that build and at this project's `samconfig.toml`
by absolute path:

```powershell
sam build --template infrastructure\template.yaml --build-dir C:\sam-build\moodjournal
sam deploy --template-file C:\sam-build\moodjournal\template.yaml --config-file "$PWD\samconfig.toml"
```

### 2. Generate a JWT secret

The template requires at least 32 characters:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 3. Deploy the stack

```powershell
sam deploy --guided
```

| Prompt | Value |
|---|---|
| Stack Name | `moodjournal-stack` |
| AWS Region | `us-east-1` |
| Environment | `dev` |
| GeminiApiKey | your Gemini key |
| JwtSecret | the string generated above |
| CorsAllowedOrigin | `*` — tightened in step 5 |
| LogLevel | `INFO` |
| Allow SAM CLI IAM role creation | `Y` |
| `Health` / `Register` / `Login` may not have authorization defined | `y` — these are intentionally public |

The first deployment takes 10–15 minutes; the CloudFront distribution is the slow part.

`samconfig.toml` stores your answers, including both secrets in plaintext. It is gitignored —
keep it that way.

### 4. Configure and publish the frontend

```powershell
.\scripts\deploy_frontend.ps1 -StackName moodjournal-stack -Region us-east-1
```

Reads the stack outputs, writes the API Gateway URL into `frontend/js/config.js`, uploads the
frontend to S3 and invalidates the CloudFront cache. No HTML or JS is edited by hand.

### 5. Lock down CORS

The CloudFront URL does not exist until the stack has been created, so the first deployment
allows any origin. Once you have the `CloudFrontUrl` output:

```powershell
sam deploy --parameter-overrides CorsAllowedOrigin=https://YOUR-ID.cloudfront.net
```

### 6. Seed demo data (optional)

```powershell
python scripts\seed_demo_data.py --invoke-scheduled
```

Creates `demo.user` / `DemoPass123` with two weeks of back-dated entries, then invokes the
deployed weekly-reflection Lambda so the automatic reflection can be demonstrated without waiting
for the schedule. Entries carry preset moods and are written straight to DynamoDB, so seeding
costs **zero Gemini API calls**.

`--show` reads the stored reflections back; `--cleanup` removes the demo account and its items.

---

## 📚 API Endpoints

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | public | Liveness check |
| POST | `/auth/register` | public | Create an account |
| POST | `/auth/login` | public | Sign in, returns a JWT |
| GET | `/auth/me` | required | Current user |
| POST | `/auth/change-password` | required | Change password |
| POST | `/entries` | required | Create an entry (classifies mood) |
| GET | `/entries` | required | List entries — `mood`, `startDate`, `endDate`, `search`, `limit`, `nextToken` |
| GET | `/entries/{entryId}` | required | Get one entry |
| PUT | `/entries/{entryId}` | required | Update an entry (re-classifies) |
| DELETE | `/entries/{entryId}` | required | Delete an entry |
| GET | `/dashboard` | required | Aggregated stats — `period` = 7d / 14d / 30d / 90d |
| POST | `/reflections` | required | Generate a reflection |
| GET | `/reflections` | required | List reflections |
| POST | `/analytics/export` | required | Export the caller's last 90 days to S3 (also runs daily for everyone) |
| GET | `/analytics/athena` | required | Run a named Athena query — `query` = `mood_count_by_week`, `most_common_mood_by_month`, `average_mood_score_over_time` or `entry_count_by_day` |

Protected routes derive the user from the Lambda authorizer's request context, never from a value
supplied by the browser.

---

## 🗄️ DynamoDB Design

**`MoodJournalTable`** — entries and reflections in one table, separated by sort-key prefix:

```
PK = USER#{userId}
SK = ENTRY#{entryDate}#{entryId}
SK = REFLECTION#{createdAt}#{reflectionId}
```

Sorting by `SK` therefore sorts by date, which is what the history page needs. Both kinds live in
one partition, so a single query retrieves everything belonging to one user.

Entry attributes: `entityType`, `entryId`, `userId`, `title`, `content`, `entryDate`, `mood`,
`moodScore`, `confidence`, `shortReason`, `classificationFallback`, `searchText`, `createdAt`,
`updatedAt`.

`searchText` is a lowercased copy of the title and content. DynamoDB has no text index and its
`contains` operator is case-sensitive, so the folded value has to be stored for search to work.

**`MoodJournalUsers`** — partition key `userId`, with a `UsernameIndex` GSI on `username` so login
is a query rather than a table scan.

---

## 🔐 Security

- **No credentials in code** — secrets arrive as CloudFormation parameters and Lambda environment variables
- **Passwords hashed with scrypt** — memory-hard, standard library, never stored in plaintext
- **`passwordHash` never leaves the backend** — omitted from every API response
- **Identity from the authorizer** — handlers read the verified user id from the request context
- **Generic login errors** — a wrong password and an unknown username are indistinguishable
- **Least-privilege IAM** — each function is granted only the tables and buckets it uses
- **No journal text in logs** — only lengths are logged
- **Journal text stays out of analytics** — the S3 export carries content *length*, never content
- **No caller-supplied SQL** — the Athena route accepts only a query name from an allow-list, and
  the user id is passed as an execution parameter
- **`.env`, `samconfig.toml` and `.aws-sam/` are gitignored**

---

## 🧹 Cleanup

```powershell
python scripts\seed_demo_data.py --cleanup
```

```powershell
sam delete --stack-name moodjournal-stack --region us-east-1
```

`sam delete` removes every resource in the stack. The S3 buckets must be emptied first if they
still contain objects.

---

## 📖 Known Limitations

- Reflections and classification depend on the Gemini API; the free tier allows 20 requests per
  day, shared between the two
- Journal entries are protected by DynamoDB's server-side encryption at rest, but not
  additionally encrypted per user
- Athena partition projection is configured for the years 2026–2035
- *Long-term Insights* reads the S3 export, so it lags DynamoDB until the next daily export or a
  press of *Export Latest Entries*
- A deleted entry remains in earlier exports and can still appear in Athena results
- No password reset flow, by design — authentication is deliberately self-contained

---

## 📝 License

MIT

---

## 👤 Author

Rachel Huynh
