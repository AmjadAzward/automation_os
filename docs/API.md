# API reference (local prototype)

**GET** `/api/health`, `/api/overview`, `/api/comparison`, `/api/tasks`, `/api/quotations`, `/api/contracts`, `/api/tariffs`, `/api/transactions`, `/api/exceptions`, `/api/audit`.

**POST** `/api/tasks`, `/api/quotations`, `/api/contracts`, `/api/tariffs`, `/api/transactions`: JSON object matching UI fields.

**POST** `/api/status`: `{"table":"tasks|contracts|exceptions","id":1,"status":"open|in_progress|blocked|done"}`.

**POST** `/api/scan`: `{}` — scans due dates and tariff underbilling.

**POST** `/api/import`: `{"table":"tasks","csv":"title,department,...\n..."}`.

**POST** `/api/ai`: `{"prompt":"Explain these terms..."}` — requires local Ollama.

No authentication is implemented. **Never expose this API outside the trusted local machine.**
