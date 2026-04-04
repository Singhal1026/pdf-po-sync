# pdf-po-sync

> LLM-powered pipeline to extract, map, and sync multi-vendor purchase orders into ERP.

A production-ready, extensible pipeline that watches a shared drive for incoming vendor PO PDFs, uses an LLM to extract structured item data, maps it against a reference master, and uploads it directly to **Infor LN ERP** via a BW session — all with zero manual intervention.

---

## 🚀 Features

- **Multi-vendor support** — handles Croma (Infiniti Retail), Reliance Retail, and Zepto out of the box
- **LLM-powered extraction** — uses Groq (Llama 3.3 70B) to parse complex PO tables from raw PDF text
- **Plug-and-play architecture** — add a new vendor by writing one handler class; nothing else changes
- **ERP auto-upload** — drives Infor LN BW sessions via subprocess automation
- **Resilient pipeline** — per-file error isolation, retry logic, structured logging with rotation
- **Config-driven** — all paths, credentials, and toggles live in `config.ini`; no code changes needed for deployment

---

## 🗂️ Project Structure

```
pdf-po-sync/
├── handlers/
│   ├── __init__.py          # Handler registry — add new vendors here
│   ├── base_handler.py      # Abstract base class for all handlers
│   ├── croma.py
│   ├── reliance.py
│   ├── zepto.py
│   └── prompts/
│       ├── croma.txt        # LLM prompt for Croma POs
│       ├── reliance.txt
│       └── zepto.txt
├── main.py                  # Pipeline entry point
├── pdf_extractor.py         # PDF text extraction + handler routing
├── llm_client.py            # Groq API client with retry logic
├── erp_runner.py            # Infor LN BW session runner
├── logger.py                # Rotating file + console logger setup
├── config_example.ini       # ← copy this to config.ini and fill in values
├── requirements.txt
└── README.md
```

---

## ⚙️ Setup

### 1. Clone the repository

```bash
git clone https://github.com/Singhal1026/pdf-po-sync.git
cd pdf-po-sync
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure

```bash
cp config_example.ini config.ini
```

Edit `config.ini` with your environment values:

```ini
[paths]
shared_drive_path = \\server\shared\po-inbox
input_dir         = data\input
output_csv        = output\output.csv
reference_xlsx    = data\RC_Portal_Details.xlsx
log_file          = logs\pipeline.log
excel_output_path = output\output.xlsx

[erp]
upload_in_erp = yes
bw_exe        = C:\Path\To\bw.exe
bwc_file      = C:\Path\To\session.bwc
session       = your_session_id

[llm]
groq_api_key = your_groq_api_key_here

[pipeline]
delete_from_shared_drive_after_copy = no
delete_local_input_after_processing = no
```

### 4. Prepare the reference Excel

The pipeline expects `RC_Portal_Details.xlsx` with one sheet per vendor:

| Sheet Name        | Used By          |
|-------------------|------------------|
| `Croma_Details`   | CromaHandler     |
| `Reliance_Details`| RelianceHandler  |
| `Zepto_Details`   | ZeptoHandler     |

Each sheet must contain columns: `Article code`, `KENT SKU`, `BP CODE`, `Address Code`, `facility_name 2`, `Emp Code`, `W/H Code`.

---

## ▶️ Running the Pipeline

```bash
python main.py
```

The pipeline will:

1. Copy all PDFs from `shared_drive_path` → `input_dir`
2. Identify the vendor for each PDF
3. Extract DC/site code and PO number via regex
4. Extract the items table using the LLM
5. Map items against the reference Excel
6. Concatenate all results into `output.csv`
7. Upload to Infor LN ERP via BW session
8. Optionally clean up local and shared drive files

---

## 🏗️ Adding a New Vendor

1. Create `handlers/your_vendor.py` extending `BaseHandler`:

```python
from base_handler import BaseHandler

class YourVendorHandler(BaseHandler):

    @property
    def company_name(self): return "Your Vendor Pvt Ltd"

    @property
    def portal_name(self): return "YourVendor"

    @property
    def reference_sheet(self): return "YourVendor_Details"

    def identify(self, full_text): 
        return "your vendor pvt ltd" in full_text.lower()

    def extract_metadata(self, full_text, pdf_path):
        # regex for dc_code and po_num
        ...

    def extract_table(self, pdf_path, full_text, api_key):
        # call LLM with your prompt
        ...

    def preprocess(self, items, po_num, dc_code, ref_path):
        # merge with reference sheet
        ...
```

2. Create `handlers/prompts/your_vendor.txt` with the extraction prompt.

3. Register the handler in `handlers/__init__.py`:

```python
from handlers.your_vendor import YourVendorHandler

HANDLERS = [
    CromaHandler(),
    RelianceHandler(),
    ZeptoHandler(),
    YourVendorHandler(),   # ← add here
]
```

That's it. No changes to the pipeline core.

---

## 📋 Logging

Logs are written to `logs/pipeline.log` (rotating, max 5 MB, last 3 files kept) and mirrored to the console.

```
2025-04-04 10:32:01 | INFO     | main            | Pipeline started
2025-04-04 10:32:03 | INFO     | pdf_extractor   | Matched handler: Infiniti Retail Limited
2025-04-04 10:32:09 | INFO     | croma           | LLM extracted 14 rows for Croma
2025-04-04 10:32:10 | INFO     | main            | output.csv saved (14 rows)
2025-04-04 10:32:15 | INFO     | erp_runner      | Success: Excel report generated
```

---

## 🔒 Security Notes

- Store all credentials in `config.ini` only — never hardcode API keys or session IDs
- `config.ini` is excluded from version control via `.gitignore`
- The reference Excel (`RC_Portal_Details.xlsx`) contains internal SKU and BP mappings — do not commit it either

---

## 🛠️ Tech Stack

| Component        | Technology                        |
|------------------|-----------------------------------|
| PDF Parsing      | `pdfplumber`                      |
| LLM Extraction   | Groq API (Llama 3.3 70B)          |
| Data Processing  | `pandas`                          |
| ERP Integration  | Infor LN via BW subprocess        |
| Retry Logic      | `tenacity`                        |
| Config           | `configparser`                    |
