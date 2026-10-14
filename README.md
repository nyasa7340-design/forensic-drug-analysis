# forensic-drug-analysis

An HTML/CSS/JavaScript frontend connected to the existing Python spectral analysis engines. The interface uses a lavender/white palette, dark-purple controls, an optimized generated laboratory photograph, and a vertically scrolling translucent workspace. All eight features use real library data and persistent local records.

## Run locally

For Vercel frontend + Render backend deployment, follow [DEPLOYMENT.md](DEPLOYMENT.md).

Use Python 3.10 or later from the repository directory:

```powershell
python -m pip install -r requirements.txt
python server.py --port 8503
```

Open http://127.0.0.1:8503. To use another port, change `--port`. The frontend and API share one local origin; no Node.js installation, frontend build step, account, or API key is required. Opening `frontend/index.html` directly is insufficient because the real calculations require the local API.

The previous Streamlit `streamlit_app.py` remains available for compatibility, but `server.py` is the entry point for the new interface. Run only one server on a given port.

## Structure

```text
forensic-drug-analysis/
├── server.py                       # Local API and static frontend server
├── frontend/
│   ├── index.html                  # Semantic pages and accessible forms
│   ├── styles.css                  # Responsive lavender glass design system
│   ├── assets/
│   │   └── laboratory.webp         # Optimized generated laboratory background
│   └── js/
│       ├── api.js                  # API transport, file uploads and downloads
│       ├── components.js           # Tables, charts and real analysis reports
│       ├── notebook.js             # Evidence notebook components and workflows
│       └── app.js                  # Navigation and feature controllers
├── analysis_core.py                # Validated parser and spectral fitting
├── simulation_core.py              # Reproducible signal experiments
├── evidence_notebook.py            # Persistent case store and integrity checks
├── swgdrug_library.csv             # Bundled reference metadata
├── swgdrug_features.csv            # Bundled spectral vectors
├── requirements.txt
└── __pycache__/
    ├── analysis_history.sqlite3    # Existing saved runs, retained
    └── evidence_notebooks/         # Existing case records, retained
```

## Features

1. Overview: actual library, analysis and notebook counts; recent saved runs.
2. Spectrum analysis: reference, manual peaks and multi-record file inputs; matching, NNLS fit, signed residuals and report exports.
3. Mixture simulator: two/three signals, measurement disturbances, reproducible seeds, blind library recovery, fingerprint diagnostics and controlled ratio sweeps.
4. Batch upload: up to 50 spectra with individual file errors and full report downloads.
5. Reference library: literal search, molecular-mass filters, pagination, spectra and CSV exports.
6. History: restore and export existing persistent runs.
7. Evidence notebook: analysis snapshots, supporting attachments, peak observations, conflicting findings, review notes and HTML/JSON/ZIP case exports.
8. Methodology: actual equations, thresholds, data provenance and interpretation limits.

No fabricated data or confidence claims are used. Empty-state text is clearly identified. The peak-list placeholder is an example format only. Supporting chromatogram/FTIR attachments are retained for manual review; they are not automatically interpreted.

## Accessibility and implementation

Semantic landmarks, descriptive labels, a skip link, keyboard menu/navigation, focus indicators, status/error announcements, reduced-motion support and accessible SVG chart descriptions are included. The decorative background is hidden from assistive technology. Main text uses AA-contrast dark colours against near-white surfaces. The panel has an independent slim scrollbar, while the laboratory image stays fixed.

User-supplied names and notes are escaped before HTML rendering; uploads are size-limited and processed locally. Evidence files retain SHA-256 checksums. The server listens on 127.0.0.1 and rejects cross-origin JSON mutations. It is a local workstation app; an internet deployment would require a separate authentication, authorization and operations design.

## Checks

```powershell
python -m unittest test_frontend_api -v
node --test frontend/js/components.test.js
```

Node.js is optional and is used only for the JavaScript component checks. API tests use isolated history/notebook storage and real reference data. Existing scientific-engine and notebook tests remain in the repository.

## Interpretation

Cosine similarity is not a calibrated identity probability. NNLS coefficients are relative spectral fit weights, not mass fractions, concentration or purity. Exact duplicates and nonunique solutions require review. Synthetic sweeps are exploratory, not validated detection limits. Review status is analyst-entered; the local notebook activity log is not a tamper-proof chain of custody.
