# MoodJournal — AI-Powered Personal Journal with Sentiment Trends

An intelligent journaling application that automatically analyzes your mood and surfaces patterns over time without requiring manual tagging or reflection.

**Status:** Local application feature-complete for pre-AWS testing. AWS deployment remains a separate final phase.

---

## Run the complete local version first

On Windows, double-click `START_APP.cmd`, or run it from Command Prompt. It creates the Python 3.14 virtual environment, installs local dependencies, starts the RAM backend and frontend, and opens the registration page. No AWS credentials are required.

For detailed local testing instructions, see `LOCAL_TEST_README.md`.

> Local data is intentionally stored in RAM and is cleared whenever the backend restarts.

---

## 🎯 Features

- **Free-form journaling** — Write naturally without structure
- **Automatic mood classification** — Gemini when configured; explicit offline fallback for local testing
- **Mood trends dashboard** — Visualize emotional patterns week-by-week
- **AI-written reflections** — Periodic summaries of recent mood patterns
- **Data analytics** — Local dashboard now; Amazon Athena remains for the AWS deployment phase
- **Cloud-ready architecture** — AWS Lambda/API Gateway/DynamoDB/S3/CloudFront/Athena source remains for the final deployment phase

---

## 🏗️ Architecture

```
Browser (HTML5/CSS3/Vanilla JS)
    ↓
CloudFront (CDN)
    ↓
S3 (Static Frontend)
    ↓
API Gateway (REST)
    ↓
AWS Lambda (Python 3.14)
    ├→ Google Gemini API
    ├→ DynamoDB
    ├→ S3 Analytics
    └→ Athena
```

**AWS Services:**
- Lambda (compute)
- API Gateway (REST API)
- DynamoDB (entries & reflections)
- S3 (frontend + analytics export)
- CloudFront (CDN)
- Athena (SQL analytics)
- EventBridge (scheduled reflections)

**Third-party:**
- Google Gemini API (sentiment classification)

---

## 📋 Mood Categories

- `POSITIVE` — Optimistic, happy, accomplished
- `NEUTRAL` — Calm, balanced, factual
- `ANXIOUS` — Worried, uncertain, stressed
- `NEGATIVE` — Sad, frustrated, discouraged

---

## 🛠️ Tech Stack

**Backend:**
- Python 3.14
- AWS Lambda
- boto3
- google-generativeai

**Frontend:**
- HTML5
- CSS3
- Vanilla JavaScript
- Vanilla JavaScript + native SVG/CSS charts (no chart CDN required locally)

**Infrastructure:**
- AWS SAM (Serverless Application Model)
- CloudFormation

---

## 📁 Project Structure

```
moodjournal/
├── frontend/                  # HTML5/CSS3/Vanilla JS
│   ├── index.html
│   ├── history.html
│   ├── dashboard.html
│   ├── reflection.html
│   ├── css/
│   │   └── styles.css
│   └── js/
│       ├── config.example.js
│       ├── api.js
│       ├── entry.js
│       ├── history.js
│       ├── dashboard.js
│       ├── reflection.js
│       └── common.js
│
├── backend/                   # Python 3.14 Lambda handlers
│   ├── handlers/
│   ├── services/
│   ├── repositories/
│   ├── models/
│   ├── utils/
│   ├── requirements.txt
│   └── requirements-dev.txt
│
├── infrastructure/
│   ├── template.yaml          # AWS SAM template
│   └── athena/
│       ├── create_database.sql
│       ├── create_table.sql
│       └── example_queries.sql
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── scripts/
│   ├── check-python-version.py
│   ├── setup-env.sh           # macOS/Linux
│   ├── setup-env.ps1          # Windows
│   └── deploy.sh
│
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## 🔧 Setup

### Prerequisites

- **Python 3.14+** — Required for Lambda runtime
- **AWS Account** — For cloud deployment
- **Google Gemini API Key** — For mood classification
- **AWS SAM CLI** — For local development and deployment

### 1. Clone and Navigate

```bash
cd moodjournal
```

### 2. Create Virtual Environment

**Windows (PowerShell):**
```powershell
.\scripts\setup-env.ps1
```

**macOS/Linux:**
```bash
bash scripts/setup-env.sh
```

**Manual:**
```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# or
.venv\Scripts\Activate.ps1       # Windows
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt
```

### 3. Verify Python Version

```bash
python scripts/check-python-version.py
```

Expected output:
```
Python version: 3.14.x
✅ Python version requirement met (3.14+)
```

### 4. Environment Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Edit `.env` with:
- `AWS_REGION`
- `GEMINI_API_KEY`
- `DEMO_USER_ID`

**Never commit `.env`** — it contains secrets.

---

## 🧪 Testing

```bash
# Run unit tests
pytest

# Run with coverage
pytest --cov=backend

# Run specific test
pytest tests/unit/test_validation.py
```

---

## 🔍 Code Quality

```bash
# Check code style
ruff check .

# Format code
ruff format .

# Type checking
mypy backend
```

---

## ☁️ Deployment

### Local Development

```bash
# Check Python version
python scripts/check-python-version.py

# Build Lambda functions
sam build

# Run locally
sam local start-api
```

Frontend: Open `frontend/index.html` in a browser.

### AWS Deployment

```bash
# Validate template
sam validate

# Build
sam build

# Deploy (interactive)
sam deploy --guided

# Deploy (non-interactive, with prior config)
sam deploy
```

---

## 📚 API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/entries` | Create journal entry |
| GET | `/entries` | List entries (with filters) |
| GET | `/entries/{id}` | Get single entry |
| PUT | `/entries/{id}` | Update entry |
| DELETE | `/entries/{id}` | Delete entry |
| GET | `/dashboard` | Dashboard stats |
| POST | `/reflections` | Generate reflection |
| GET | `/reflections` | List reflections |
| POST | `/analytics/export` | Export analytics to S3 |
| GET | `/analytics/athena` | Run Athena query |
| GET | `/health` | Health check |

---

## 🗄️ DynamoDB Design

**Table:** `MoodJournalTable`

**Partition Key:** `PK` (e.g., `USER#demo-user`)  
**Sort Key:** `SK` (e.g., `ENTRY#2026-08-06#uuid`)

**Attributes:**
- `entityType` — ENTRY or REFLECTION
- `entryId` — UUID
- `userId` — User identifier
- `title` — Optional entry title
- `content` — Journal text (1–5,000 characters)
- `entryDate` — Date of entry
- `mood` — POSITIVE | NEUTRAL | ANXIOUS | NEGATIVE
- `moodScore` — Numeric for charts (2, 1, 0, -1)
- `confidence` — 0.0–1.0 from Gemini
- `shortReason` — Non-clinical explanation
- `classificationFallback` — True if fallback to NEUTRAL
- `createdAt` — ISO-8601 timestamp (UTC)
- `updatedAt` — ISO-8601 timestamp (UTC)

---

## 🔐 Security

- **No credentials in code** — Use AWS Secrets Manager or environment variables
- **Input validation** — All user input validated server-side
- **Output escaping** — Frontend escapes HTML
- **CORS restrictions** — API accepts only approved origins
- **Least-privilege IAM** — Lambda has minimal required permissions
- **No full journal in logs** — Sensitive content excluded from CloudWatch
- **Environment secrets** — `.env` in `.gitignore`

---

## ⚠️ Files That Must Never Be Committed

- `.env` (contains API keys and secrets)
- `.venv/` (Python virtual environment)
- `.aws-sam/` (SAM build artifacts)
- `__pycache__/` (Python cache)
- `*.log` (Log files)
- `node_modules/` (if using npm)
- `.idea/`, `.vscode/` (IDE configs)

---

## 🚀 Demo Walkthrough

1. **Navigate to frontend:**
   ```bash
   open frontend/index.html  # macOS
   explorer frontend/index.html  # Windows
   ```

2. **Create an entry:**
   - Click "New Entry"
   - Write about your day
   - Click "Save and Analyse"
   - See detected mood

3. **View history:**
   - Click "History"
   - Filter by mood or date
   - View entry details

4. **View dashboard:**
   - Click "Dashboard"
   - See mood statistics and trends
   - View last 7 days

5. **Generate reflection:**
   - Click "Reflection"
   - Select time period
   - Read AI-generated summary

---

## 📖 Known Limitations

- Demo mode (no user authentication)
- Single user (`demo-user`)
- Entries not encrypted at rest (for demo)
- Limited to Gemini API rate limits

---

## 🧹 AWS Resource Cleanup

To remove all AWS resources after testing:

```bash
# List CloudFormation stacks
aws cloudformation list-stacks --region ap-southeast-2

# Delete stack
aws cloudformation delete-stack \
  --stack-name moodjournal-stack \
  --region ap-southeast-2

# Monitor deletion
aws cloudformation wait stack-delete-complete \
  --stack-name moodjournal-stack \
  --region ap-southeast-2

echo "✅ Stack deleted"
```

---

## 📝 License

MIT

---

## 👤 Author

Rachel Huynh

---

**Last Updated:** Phase 2 — Project Skeleton  
**Next:** Phase 3 — Infrastructure (SAM template)
