# 📝 Savio Ng – Interactive HTML Résumé (Backend)

This is the backend for my [HTML Resume Website](https://mycv.saviong.com).  
It is built with **Azure Functions (Python)** and integrates with **Azure Cosmos DB (Table API)** to provide a live visitor counter feature.


## 🚀 Overview

- **Frontend**: Static website hosted on Azure Storage with CDN + Front Door ([repo here](https://github.com/saviong/html-resume-frontend)).
- **Backend**: Azure Function App (Python) that exposes a REST API for counting visitors.
- **Database**: Azure Cosmos DB (Table API) to persist unique visitors and the total visit count.
- **CI/CD**: Automated deployments with GitHub Actions and ARM templates.


## ⚙️ How It Works

1. A visitor loads the [resume site](https://mycv.saviong.com).

2. The frontend JavaScript makes a call to the backend Function App endpoint: `https://<function-app>.azurewebsites.net/api/updateCounter`

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

- `local.settings.json` → Local development settings (not used in production).

- `template.json` & `parameters.json` → ARM templates for deploying Azure resources.

- `.github/workflows/deploy.yml` → GitHub Actions pipeline for CI/CD.


## 🔑 Environment Variables

The Function App relies on the following application settings in Azure:

- `COSMOS_CONNECTION_STRING` → Connection string for Cosmos DB (Table API).

- `TABLE_NAME` → Name of the table storing visitor counts (default: `VisitorCounter`).


## 🛠️ Deployment Flow (GitHub Actions)

1. Checkout code.

2. Install dependencies & run tests.

3. Deploy ARM template → ensures Azure resources exist.

4. Package Python code and vendor dependencies into a zip.

5. Deploy to Azure Function App with `az functionapp deployment source config-zip`.

6. Verify that the function endpoint is active.


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
  <img src="docs/htmlresume.drawio.png" alt="Infrastructure Diagram" width="800">
</p>
