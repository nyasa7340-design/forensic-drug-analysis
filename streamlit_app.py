from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid
import os
from contextlib import contextmanager

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from analysis_core import MZ, analyze, load_library, normalize, parse_spectra
from simulator import render_simulator
from evidence_notebook import render_notebook

ROOT = Path(__file__).resolve().parent
if not (ROOT / "swgdrug_library.csv").exists():
    ROOT = ROOT.parent.parent  # Also supports the review copy in __pycache__/site_release.
STORE = Path(os.environ.get("SPECTRALAB_HISTORY_PATH", str(ROOT / "__pycache__" / "analysis_history.sqlite3")))
st.set_page_config(page_title="SpectraLab · Forensic spectral analysis", page_icon="🔬", layout="wide")
st.markdown("<style>" + Path(__file__).with_name("theme.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


@st.cache_resource
def data():
    return load_library(ROOT)


@st.cache_data
def spectral_digest():
    return hashlib.sha256((ROOT / "swgdrug_features.csv").read_bytes()).hexdigest()


@contextmanager
def connection():
    STORE.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(STORE, timeout=15)
    conn.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, timestamp TEXT, sample TEXT, source TEXT, report TEXT)")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def history():
    with connection() as conn:
        return pd.read_sql_query("SELECT id,timestamp,sample,source FROM runs ORDER BY timestamp DESC LIMIT 500", conn)


def execute(vector, name, source, simulation=None, excluded_peak_count=0, simulation_settings=None):
    with st.spinner("Comparing reference spectra and fitting candidate signals…"):
        report = analyze(vector, library, matrix)
        report.update({"run_id": uuid.uuid4().hex, "timestamp": datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec="seconds"),
                       "sample": name, "source": source, "simulation": simulation,
                       "library_version": "SWGDRUG 3.14 (bundled)", "library_sha256": library_digest,
                       "excluded_peak_count": excluded_peak_count,
                       "simulation_settings": simulation_settings,
                       "interpretation": "Screening library comparison. Fit weights are relative coefficients of base-peak-normalized spectra, not concentration, purity or identity probabilities."})
        with connection() as conn:
            conn.execute("INSERT INTO runs VALUES (?,?,?,?,?)", (report["run_id"], report["timestamp"], name, source, json.dumps(report, allow_nan=False)))
        st.session_state.report = report
    st.success("Analysis saved. Review the results below or restore it from History.")
    return report


def spectrum_plot(query, reconstructed=None, residual=None, reference=None):
    panels = 3 if reconstructed is not None else 1
    fig, axes = plt.subplots(panels, 1, figsize=(12, 3.0 if panels == 1 else 6.2), sharex=True, squeeze=False)
    values = [(np.asarray(query), "Input spectrum", "#137780")]
    if reconstructed is not None:
        values += [(np.asarray(reconstructed), "Reconstructed candidate fit", "#4669be"), (np.asarray(residual), "Residual · input minus fit", "#cf7955")]
    for ax, (vector, label, color) in zip(axes[:, 0], values):
        mask = np.abs(vector) > 1e-8
        ax.vlines(MZ[mask], 0, vector[mask], color=color, linewidth=1.1)
        ax.axhline(0, color="#a2aebb", lw=.7)
        ax.set_title(label, loc="left", fontsize=10, color="#30445d", pad=10)
        ax.set_ylabel("Relative intensity", fontsize=9)
        ax.grid(axis="y", alpha=.15)
        ax.spines[["top", "right"]].set_visible(False)
        if label.startswith("Residual"):
            bound = max(2, float(np.max(np.abs(vector))) * 1.15)
            ax.set_ylim(-bound, bound)
        else:
            ax.set_ylim(0, max(110, float(vector.max()) * 1.1))
    if reference is not None:
        axes[0, 0].vlines(MZ, 0, -np.asarray(reference), color="#4669be", linewidth=.9, label="Best reference (mirrored)")
        axes[0, 0].set_ylim(-110, 110)
        axes[0, 0].legend(loc="upper right", fontsize=8)
    axes[-1, 0].set_xlabel("m/z · nominal mass bins (10–550)")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def render_report(report, key):
    st.divider()
    st.subheader("Analysis results")
    st.caption(f"{report['sample']} · {report['source']} · {report['timestamp']}")
    if report.get('excluded_peak_count', 0):
        st.warning(f"{report['excluded_peak_count']} JCAMP peaks outside m/z 10–550 were excluded. Matches describe only the supported range.")
    a, b, c, d = st.columns(4)
    a.metric("Best cosine similarity", f"{report['cosine_similarity']:.4f}")
    b.metric("Fit R²", f"{report['r_squared']:.4f}" if report['r_squared'] is not None else "Undefined")
    c.metric("Fit RMSE", f"{report['rmse']:.3f}")
    d.metric("Residual / input norm", f"{report['relative_residual'] * 100:.2f}%")
    with st.container(border=True):
        st.markdown(f"**{report['status']}**")
        st.subheader(report["best_name"])
        row = library[library.id == report["best_entry_id"]].iloc[0]
        st.caption(f"Local entry #{row.id} · Formula: {row.formula} · Molecular mass: {row.mw:g} Da · Base peak: m/z {row.base_peak_mz}")
        if len(report["exact_match_entry_ids"]) > 1:
            st.warning(f"Multiple entries share this exact spectral match: {report['exact_match_entry_ids']}. The spectrum cannot distinguish them.")
        if report["cosine_similarity"] < .85:
            st.warning("The best single-reference match is weak. Treat the result as inconclusive; a fitted combination does not establish identity.")
        if report["peak_count"] < 5:
            st.warning("Fewer than five populated mass bins: limited evidence for a specific library assignment.")
        st.caption("Similarity measures spectral shape. It is not a probability of correct identification. A single fitted component does not establish purity.")
    results = st.tabs(["Spectra & residuals", "Ranked matches", "Candidate fit weights", "Peak data & export"])
    with results[0]:
        spectrum_plot(report["query"], report["reconstructed"], report["residual"])
        with st.expander("Compare input with the best reference"):
            index = library.index[library.id == report["best_entry_id"]][0]
            spectrum_plot(report["query"], reference=matrix[index])
    with results[1]:
        st.dataframe(pd.DataFrame(report["matches"]), hide_index=True, width='stretch',
                     column_config={"cosine_similarity": st.column_config.NumberColumn("Cosine similarity", format="%.5f")})
        st.caption("Ranks use cosine similarity across all 541 bins; ties use library row order. Local entry IDs uniquely identify rows; the source label SWGDRUG 3.14 is shared.")
    with results[2]:
        st.info("Fit weights describe the mathematical reconstruction only. Concentration and mass fractions require calibration and compound response factors.")
        components = pd.DataFrame(report["components"])
        if not components.empty:
            st.dataframe(components, hide_index=True, width='stretch', column_config={"fit_weight_percent": st.column_config.NumberColumn("Relative fit weight (%)", format="%.4f"), "coefficient": st.column_config.NumberColumn("NNLS coefficient", format="%.6f")})
        else:
            st.info("No candidate contributed to the fit.")
        st.caption(f"{report['candidate_count']} candidate spectra fitted. All positive coefficients are included. Similar reference spectra may have nonunique solutions.")
    with results[3]:
        frame = pd.DataFrame({"mz": MZ, "input": report["query"], "reconstructed": report["reconstructed"], "residual": report["residual"]})
        st.dataframe(frame[frame["input"] > 0], hide_index=True, width='stretch')
        a, b = st.columns(2)
        a.download_button("Download full report · JSON", json.dumps(report, indent=2, allow_nan=False), f"analysis-{report['run_id'][:8]}.json", "application/json", key=f"{key}_json")
        b.download_button("Download spectra · CSV", frame.to_csv(index=False), f"spectra-{report['run_id'][:8]}.csv", "text/csv", key=f"{key}_csv")


try:
    library, matrix = data()
    library_digest = spectral_digest()
    saved = history()
except (ValueError, OSError, sqlite3.Error) as exc:
    st.error(f"Could not initialize the library or local history: {exc}")
    st.stop()

st.markdown('<div class="brand"><span class="brand-icon">SL</span>SpectraLab<small>Local analysis workspace</small></div>', unsafe_allow_html=True)
st.markdown('<div class="hero"><div><h1>Spectral analysis</h1><p>Compare reference spectra, inspect mixture fits, and keep an analysis record.</p></div><div class="hero-meta"><strong>SWGDRUG 3.14</strong><br>m/z 10–550 · Reference screening</div></div>', unsafe_allow_html=True)

overview, analysis_tab, simulator, batch, explorer, history_tab, notebook_tab, methodology = st.tabs(["Overview", "Spectrum analysis", "Mixture simulator", "Batch upload", "Reference library", "History", "Evidence notebook", "Methodology"])
options = list(range(len(library)))


def label(index):
    row = library.iloc[index]
    return f"{row['name']} · #{row['id']} · {row['formula']}"


with overview:
    st.subheader("Workspace overview")
    a, b, c = st.columns(3)
    a.metric("Reference spectra", f"{len(library):,}")
    b.metric("Mass channels", f"{len(MZ)}")
    c.metric("Saved analyses", len(saved), help="Latest 500 local records shown in History.")
    st.write("")
    a, b, c = st.columns(3)
    with a, st.container(border=True):
        st.markdown("### Spectrum comparison")
        st.write("Select a reference, paste measured peaks, or upload a spectrum. Inspect ranked matches and unexplained peaks.")
        st.caption("Open Spectrum analysis to begin.")
    with b, st.container(border=True):
        st.markdown("### Mixture experiments")
        st.write("Mix two or three reference signals, introduce measurement challenges, and explore how well the inputs can be recovered.")
        st.caption("Open Mixture simulator to experiment.")
    with c, st.container(border=True):
        st.markdown("### Records & references")
        st.write("Browse the library, process multiple files, restore saved runs, and download spectra and reports.")
        st.caption("Local records persist across restarts.")
    st.info("Screening results require analyst review. This workspace does not infer toxicity, seizure provenance, purity, or laboratory accreditation from a mass spectrum.")
    if "report" in st.session_state:
        report = st.session_state.report
        st.markdown(f"**Latest analysis:** {report['sample']} · {report['status']}")

with analysis_tab:
    st.subheader("Compare a mass spectrum")
    st.caption("Choose an input method. Results change only when you submit an analysis.")
    mode = st.radio("Input method", ["Reference spectrum", "Paste peaks", "Upload file"], horizontal=True)
    if mode == "Reference spectrum":
        with st.form("reference_form"):
            chosen = st.selectbox("Search reference compounds", options, format_func=label, index=1746)
            st.caption("A reference self-match checks the workflow; it does not measure performance on unknown samples.")
            submit = st.form_submit_button("Analyze reference", type="primary")
        if submit:
            execute(matrix[chosen], label(chosen), "Reference self-check")
    elif mode == "Paste peaks":
        with st.form("peaks_form"):
            sample = st.text_input("Sample name", "Measured spectrum", max_chars=150)
            peaks = st.text_area("m/z and intensity", placeholder="58:100, 91:35, 105:12\nOr one m/z,intensity pair per line", height=155)
            st.caption("m/z 10–550; finite, nonnegative intensities. Duplicate bins are summed and the largest peak is normalized to 100.")
            submit = st.form_submit_button("Analyze peaks", type="primary")
        if submit:
            try:
                spectrum = parse_spectra(peaks, sample.strip() or "Measured spectrum")[0]
                execute(spectrum.vector, spectrum.name, "Manual peak list")
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
    else:
        upload = st.file_uploader("Upload CSV or uncompressed JCAMP-DX", type=["csv", "txt", "jdx", "dx", "hpj"], key="single_upload")
        st.caption("CSV: mz,intensity. JCAMP: (XY..XY) peak tables, with optional XFACTOR/YFACTOR. Multi-record files are kept separate.")
        if upload is not None:
            try:
                records = parse_spectra(upload.getvalue(), upload.name)
                chosen_record = st.selectbox("Spectrum in file", range(len(records)), format_func=lambda i: f"{i+1}. {records[i].name} ({records[i].peak_count} bins)")
                if records[chosen_record].excluded_peak_count:
                    st.warning(f"This record has {records[chosen_record].excluded_peak_count} peaks outside m/z 10–550. These will be excluded from the analysis.")
                if st.button("Analyze uploaded spectrum", type="primary"):
                    record = records[chosen_record]
                    execute(record.vector, record.name, f"Upload: {upload.name}", excluded_peak_count=record.excluded_peak_count)
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
    if "report" in st.session_state:
        render_report(st.session_state.report, "active")
    else:
        st.info("Submit a spectrum to see ranked matches, fit diagnostics, and downloadable results.")

with simulator:
    render_simulator(library, matrix, execute, render_report)

with batch:
    st.subheader("Process multiple spectra")
    uploads = st.file_uploader("Select spectrum files", type=["csv", "txt", "jdx", "dx", "hpj"], accept_multiple_files=True, key="batch_upload")
    st.caption("Up to 50 spectra per batch. Invalid files are reported individually. Large library files can be inspected one entry at a time in Spectrum analysis.")
    if st.button("Analyze batch", type="primary", disabled=not uploads):
        parsed, errors = [], []
        for upload in uploads:
            try:
                parsed.extend((record, upload.name) for record in parse_spectra(upload.getvalue(), upload.name))
            except ValueError as exc:
                errors.append({"file": upload.name, "error": str(exc)})
        if len(parsed) > 50:
            st.error(f"This batch contains {len(parsed)} spectra. Select at most 50; no analyses were saved.")
        else:
            reports = []
            progress = st.progress(0)
            for i, (record, filename) in enumerate(parsed):
                try:
                    reports.append(execute(record.vector, record.name, f"Batch upload: {filename}", excluded_peak_count=record.excluded_peak_count))
                except (ValueError, RuntimeError) as exc:
                    errors.append({"file": filename, "error": str(exc)})
                progress.progress((i + 1) / len(parsed))
            st.session_state.batch_reports = reports
            st.session_state.batch_errors = errors
    if st.session_state.get("batch_errors"):
        st.error("Some files could not be analyzed:")
        st.dataframe(pd.DataFrame(st.session_state.batch_errors), hide_index=True, width='stretch')
    if st.session_state.get("batch_reports"):
        reports = st.session_state.batch_reports
        summary = pd.DataFrame([{k: r[k] for k in ["sample", "status", "best_name", "cosine_similarity", "rmse"]} for r in reports])
        st.dataframe(summary, hide_index=True, width='stretch')
        st.download_button("Download batch summary", summary.to_csv(index=False), "batch-summary.csv", "text/csv")
        st.download_button("Download full batch reports", json.dumps(reports, indent=2), "batch-reports.json", "application/json")
        selected = st.selectbox("Inspect a batch result", range(len(reports)), format_func=lambda i: f"{i+1}. {reports[i]['sample']}")
        render_report(reports[selected], "batch")

with explorer:
    st.subheader("Reference library")
    st.caption("Bundled SWGDRUG 3.14 · January 22, 2025. The category field was generated locally using name rules and is not a verified pharmacological classification.")
    search = st.text_input("Search by compound, formula, or local entry ID", placeholder="Try Cocaine, C17H21NO4, or 1747")
    a, b = st.columns(2)
    low = a.number_input("Minimum molecular mass (Da)", min_value=0.0, value=0.0)
    high = b.number_input("Maximum molecular mass (Da)", min_value=0.0, value=float(library.mw.max()))
    filtered = library[(library.mw >= low) & (library.mw <= high)].copy()
    if search.strip():
        query = search.strip()
        filtered = filtered[filtered['name'].str.contains(query, case=False, regex=False) | filtered.formula.str.contains(query, case=False, regex=False) | filtered.id.astype(str).eq(query)]
    st.caption(f"{len(filtered):,} of {len(library):,} entries")
    columns = ["id", "name", "formula", "mw", "base_peak_mz", "num_peaks"]
    st.dataframe(filtered[columns], hide_index=True, width='stretch')
    st.download_button("Export filtered library", filtered[columns].to_csv(index=False), "reference-library.csv", "text/csv")
    if not filtered.empty:
        index = st.selectbox("Inspect reference spectrum", filtered.index.tolist(), format_func=label)
        spectrum_plot(matrix[index])
        peaks = pd.DataFrame({"mz": MZ, "intensity": matrix[index]})
        st.download_button("Download reference peaks", peaks[peaks.intensity > 0].to_csv(index=False), f"reference-{library.iloc[index].id}.csv", "text/csv")
    else:
        st.info("No entries match these filters.")

with history_tab:
    st.subheader("Saved analysis history")
    st.caption("Saved on this computer across restarts. Browsing and changing controls do not create analysis records. Latest 500 runs shown.")
    saved = history()
    if saved.empty:
        st.info("No saved analyses yet.")
    else:
        st.dataframe(saved.drop(columns="id"), hide_index=True, width='stretch')
        st.download_button("Export history index", saved.to_csv(index=False), "analysis-history.csv", "text/csv")
        run_id = st.selectbox("Choose a saved analysis", saved.id.tolist(), format_func=lambda id: f"{saved.set_index('id').loc[id, 'timestamp']} · {saved.set_index('id').loc[id, 'sample']}")
        if st.button("Restore saved result"):
            with connection() as conn:
                stored = conn.execute("SELECT report FROM runs WHERE id=?", (run_id,)).fetchone()
            st.session_state.restored_report = json.loads(stored[0])
            st.session_state.report = st.session_state.restored_report
        if "restored_report" in st.session_state:
            render_report(st.session_state.restored_report, "restored")

with notebook_tab:
    render_notebook(Path(os.environ.get("SPECTRALAB_NOTEBOOK_DIR", str(STORE.parent / "evidence_notebooks"))), history(), connection)

with methodology:
    st.subheader("Understand the result")
    st.markdown("""
**1. Validate and normalize.** Inputs must contain finite, nonnegative intensities and at least one positive peak. Manual/CSV m/z values must lie within 10–550. Wider JCAMP records are cropped to that range; the excluded peak count is shown and exported. Nominal bins use nearest-integer rounding, with half values rounded upward. Duplicate bins are summed. The largest intensity becomes 100.

**2. Compare with every reference.** Cosine similarity measures the angle between the input and each library spectrum. Values run from 0 to 1. A score of 1 means identical spectral shape within numerical tolerance. Multiple matching entries are reported. Scores below 0.85 receive an inconclusive label; this is a screening heuristic, not a validated decision threshold.

**3. Fit candidate signals.** Nonnegative least squares minimizes the squared difference between the input and a weighted combination of reference spectra. Start with the 60 highest cosine matches and add up to 20 candidates from positive residual peaks in each of three passes. Exact duplicate spectra use a stable representative, with alternative entry IDs listed. Similar spectra can produce nonunique fits.

**4. Inspect the unexplained signal.** Residual = input minus reconstruction. RMSE is measured in normalized intensity units across all 541 bins. R² is 1 − residual sum of squares / total sum of squares; negative values are retained. Relative residual is the residual norm divided by the input norm.

**5. Interpret coefficients carefully.** Relative fit weights sum to 100% before display rounding. They describe contributions of base-peak-normalized reference spectra. They are not validated mass fractions, concentrations, purity measurements, or probabilities of identity. No purity or novel-compound conclusion follows from fit quality alone.

**What is supported.** Library comparison, mathematical signal simulation, candidate spectral fitting, residual inspection, and reproducible local reports. The imported category field comes from name-matching rules; the previous classifier used these labels, so it is not presented as verified drug identification.

**What needs additional evidence.** Confirmed chemical identity, quantitative composition, toxicological risk, source attribution, and accreditation require independent methods and validation. No seizure database or toxicology dataset is bundled here.
""")
    st.markdown("Sources: [SWGDRUG mass spectral library](https://swgdrug.org/ms.htm) · [SciPy nonnegative least squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.nnls.html)")
    st.caption(f"Spectral data SHA-256: {library_digest}")
    st.caption(f"Library checks passed: {len(library):,} aligned metadata/spectrum rows, 541 finite nonnegative channels, no empty spectra.")

st.divider()
st.caption("SpectraLab · Local reference analysis workspace · SWGDRUG 3.14 · Results support review, with limitations shown alongside the evidence.")
