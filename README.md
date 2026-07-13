# 🤖 Practical AI Data Extraction & Automation Scripts

A collection of lightweight, practical Python tools designed to automate the extraction, validation, and structuring of complex documents (invoices, bank statements, handwritten receipts, and tax forms).

### ⚠️ A Note on My Approach ("Vibe Coding")
I am not a traditional software engineer or a senior data scientist. I am a Business Administrator who leverages AI-assisted development ("Vibe Coding") to solve operational bottlenecks. 

I build these tools using practical Python, VS Code, Google Colab, and LLM APIs. My focus is not on writing overly complex or over-engineered code, but on **delivering clean, structured, and reliable data** that businesses can actually use.

---

## 🚀 Key Features & Practical Solutions

- **Multi-LLM Fallback Logic:** If the primary Cloud API fails or times out, the script automatically routes the request to a secondary provider (e.g., NVIDIA → Mistral → Qwen) or a local OCR fallback (EasyOCR), ensuring resilience in low-connectivity environments.
- **Defensive JSON Repair:** Custom regex functions to catch and fix truncated or malformed JSON outputs from LLMs before they break the data pipeline.
- **Strict Fiscal & Mathematical Validation:** Built-in logic to verify that `Base + VAT = Total`, detect auto-retention errors, and flag suspicious characters in OCR outputs.
- **Spatial Prompting for Handwritten Text:** Advanced prompt engineering techniques that guide the AI to read specific grid coordinates (e.g., "Column Left, Row 2") to accurately transcribe messy, handwritten receipts.
- **User-Friendly Local Execution:** Simple Tkinter GUIs for file selection, with a "Preview in VS Code" step before permanently saving the clean Excel/JSON file.

---

## 🛠️ Tech Stack
- **Core:** Python 3.10+, Pandas, OpenPyXL, Tkinter, Regex
- **AI / LLMs:** NVIDIA NIM, Qwen (DashScope), Mistral, Google Gemini
- **OCR & Processing:** EasyOCR, `pypdfium2`, Pillow

---

## 📂 Included Modules

| Script | Practical Use Case |
| :--- | :--- |
| `tax_withholding_processor.py` | Extracts VAT retention forms with a 3-level LLM fallback and strict mathematical validation (e.g., verifying Base + VAT = Total). |
| `receipt_transcriber.py` | Transcribes handwritten receipts using spatial grid prompting, followed by deterministic Python cleanup and chronological sorting. |
| `bank_statement_parser.py` | Parses multi-page bank statement PDFs via Vision AI, featuring defensive number cleaning (handling mixed decimal/thousand separators) and balance reconstruction. |
| `invoice_extractor.py` | A hybrid engine (Gemini Cloud + EasyOCR local fallback) for processing batches of invoices, using geometric cropping to isolate handwritten totals when cloud APIs fail. |
| `api_health_checker.py` | A universal API validator that tests endpoint connectivity, latency, and JSON response integrity, providing specific troubleshooting suggestions on failure. |


---

## ⚙️ How to Run
1. Clone the repository.
2. Install dependencies:  
   ```bash
   pip install requests pandas openpyxl pypdfium2 python-dotenv pillow easyocr google-generativeai
