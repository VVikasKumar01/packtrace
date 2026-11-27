# PackTrace AI

PackTrace AI is a local, evidence-grounded packaging data readiness proof of concept for EcoNova Consumer Electronics. It demonstrates deterministic document extraction, source traceability, normalized conflict review, transparent readiness scoring, gap screening, supplier follow-up, scenario calculations, roadmap updates, and product-level report exports.

The application is designed to work without an LLM key or internet connection. The UI uses plain JavaScript and CSS, served by FastAPI, so the demo does not need a frontend build step. This is the environment-compatible alternative to the requested React/Vite stack: no frontend packages or external runtime downloads are needed. Google Fonts are an optional enhancement; system fonts are used if offline.

## Start locally

Requires Python 3.10+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/create_samples.py
python -m uvicorn backend.app:app --reload
```

Open <http://127.0.0.1:8000>. On first import, the SQLite database at `data/packtrace.db` is initialized with the synthetic demonstration workspace. Sample evidence files are in `data/sample_documents/` and are also downloadable from Document Intelligence.

For non-Windows shells, activate the virtual environment using that shell's standard command. The server can also be launched with `uvicorn backend.app:app --host 0.0.0.0 --port 8000` for a controlled local network demo.

## Jury demo

1. Use **Start jury demo** in the left sidebar to follow the guided 10-step walkthrough.
2. In Document Intelligence, upload one of the provided XLSX, CSV, or PDF evidence files. Extraction results show source sheet/cell, row/column, or PDF page references and confidence.
3. In Reconciliation, review the deliberately different PET description and the equivalent kg/g weight pair. Resolve a conflict and inspect the readiness value update.
4. In Optimization Lab, adjust mass, dimensions, recycled content, or the illustrative carbon factor. Results recalculate from current packaging weights.
5. In Data Exports, generate JSON, CSV, or PDF for a selected product.

Everything in the supplied EcoNova organization, supplier names, supplier statements, and document fixtures is synthetic. The supplier request control prepares a draft locally and never sends it.

## Assessment and calculations

Default readiness score: `0.30 × completeness + 0.25 × evidence coverage + 0.20 × cross-source consistency + 0.15 × supplier traceability + 0.10 × assessment coverage`. Values are bounded from 0–100. The contributions and formula are shown in the dashboard. Change the weights in `data/scoring.json`; weights must be non-negative and sum to 1. The score is an internal data-readiness indicator, not a legal compliance score.

Assessment rules are deliberately simplified screening prompts. The app makes no legal pass/fail determination and does not treat a commonly recycled material as proof of recyclability. Market-specific legal interpretation, target applicability, supplier evidence, and product protection performance need expert validation.

Official reference sources are linked inside the PPWR Gap Assessment view: [Regulation (EU) 2025/40 on EUR-Lex](https://eur-lex.europa.eu/eli/reg/2025/40/oj), the [Commission Notice C/2026/3084 guidance](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52026XC03084), and the [European Commission packaging waste overview](https://environment.ec.europa.eu/topics/waste-and-recycling/packaging-waste_en). The Commission page states the Regulation applies from 12 August 2026; the Regulation has phased provisions and this POC does not encode a full statutory timeline.

Optimization is a what-if model using user-entered percentage changes. The illustrative carbon estimate is mass avoided in kg multiplied by the configured emission factor. It omits process, transport, and end-of-life effects and is not a lifecycle assessment. Validate protection and logistics before adopting a design change.

## Data processing

- XLSX: reads workbook sheets, headers, values, and cell coordinates with openpyxl. Macros are not executed.
- CSV: retains row and column references.
- Text PDF: extracts text and page references using PyMuPDF. OCR is not available for scanned PDF pages in the base setup.
- PNG/JPG: the OCR path uses pytesseract if both it and the Tesseract executable are installed. Without them, the UI reports a clear processing error and allows retry.
- Upload size limit is 12 MB; uploads are stored under `data/uploads/` with generated safe filenames. Extraction values are marked for human review and are not automatically written to component master fields.

## API overview

FastAPI docs: `/docs`.

Key routes include `/api/dashboard`, `/api/products`, `/api/packaging`, `/api/documents/upload`, `/api/reconciliation/run`, `/api/conflicts`, `/api/conflicts/{id}/resolve`, `/api/assessment/run`, `/api/assessment/findings`, `/api/optimization/simulate`, `/api/suppliers`, `/api/roadmap`, and `/api/reports/{product_id}/{json|csv|pdf}`. The app uses SQLite today; tables use explicit identifiers and relationships suitable for a later SQLAlchemy/PostgreSQL migration.

## Test and verify

```powershell
python -m unittest discover -s tests -v
```

Tests cover seeded inventory, scoring, unit normalization, reconciliation resolution, optimization, spreadsheet source locations, and report generation. A browser/server smoke check can be done with `python -m uvicorn backend.app:app --reload` and `Invoke-WebRequest http://127.0.0.1:8000/api/health` from a normal local terminal.

## POC limits

- This is a working demonstration, not a production compliance platform or an approved Digital Product Passport.
- The sample data is synthetic and the extraction pipeline is deterministic. There is no LLM adapter enabled; the app remains fully usable without one.
- Text-PDF parsing and OCR are intentionally modest; complex tables, scanned documents, and exact bounding boxes need additional parser work.
- Reconciliation fixtures demonstrate material differences and normalized units. The POC does not yet infer component identity across arbitrary suppliers or resolve every file extraction into a master component automatically.
- Authentication, production tenancy, antivirus scanning, formal PPWR rule governance, and PostgreSQL deployment are outside this local POC.
