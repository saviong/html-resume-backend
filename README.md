# 📝 Savio Ng – Interactive HTML Résumé (Backend)

This is the backend for my [HTML Resume Website](https://mycv.saviong.com).  
It is built with **Azure Functions (Python)** and integrates with **Azure Cosmos DB (Table API)** to provide a live visitor counter feature.


## 🚀 Overview

- **Frontend**: Static website ([repo here](https://github.com/saviong/html-resume-frontend)).
- **Backend**: Azure Function App (Python) that exposes a REST API for counting visitors.
- **Database**: Azure Cosmos DB (Table API) to persist unique visitors and the total visit count.
- **CI/CD**: Automated deployments with GitHub Actions and ARM templates.


## ⚙️ How It Works

1. A visitor loads the [resume site](https://mycv.saviong.com).

2. The frontend JavaScript calls the API at `/api/updateCounter`. The Function App's own hostname is `https://resumevisitor-fn-dyb9dsguddgzdzge.uksouth-01.azurewebsites.net` (the app has a unique default hostname, so the short `resumevisitor-fn.azurewebsites.net` form does not resolve).

3. The **Function App**:
- Extracts the visitor's IP.
- Checks Cosmos DB Table for whether this IP has visited before.
- If **new visitor** → increments the total count and stores the IP.
- If **already counted** → returns the current total without incrementing.

4. Returns a JSON response:
```json
{
  "count": 123
}
```

5. The frontend displays the live visitor count.


## 📂 Key Files

- `function_app.py` → Main Azure Function code (HTTP-triggered API).

- `requirements.txt` → Python dependencies (azure-functions, azure-data-tables, etc.).

- `host.json` → Function host configuration.

- `local.settings.json` → Local development settings (git-ignored, not used in production).

- `template.json` & `parameters.json` → ARM templates for deploying Azure resources.

- `.github/workflows/master_resumevisitor-fn.yml` → GitHub Actions pipeline for CI/CD.


## 🔑 Environment Variables

The Function App relies on the following application settings in Azure:

- `COSMOS_CONNECTION_STRING` → Connection string for Cosmos DB (Table API).

- `TABLE_NAME` → Name of the table storing visitor counts (default: `VisitorCounter`).

- `ALLOWED_ORIGINS` → Comma-separated CORS allowlist (default `*`). The function emits its own
  `Access-Control-Allow-Origin`, so the Function App's **platform CORS allowed-origins list must be
  left empty** — otherwise the platform adds a second header and browsers reject the response.


## 🛠️ Deployment Flow (GitHub Actions)

1. Checkout code.

2. Install dependencies & run tests.

3. Vendor dependencies into `.python_packages/`.

4. Deploy to the Azure Function App with `Azure/functions-action`.


## 🧪 Testing Locally

- Install dependencies:
```bash
pip install -r requirements.txt
```

- Run function locally:
```bash
func start
```

- Test endpoint:
```bash
curl http://localhost:7071/api/updateCounter
```

## 🚀 Infrastructure diagram

<p align="center">
  <img src="https://github.com/saviong/html-resume-frontend/blob/master/docs/htmlresume.drawio.png?raw=true" alt="Infrastructure Diagram" width="800">
</p>
