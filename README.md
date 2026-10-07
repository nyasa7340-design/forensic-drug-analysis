# 🔬 AI Forensic Drug Analysis & Mixture Deconvolution Suite

An **ISO/IEC 17025 Compliant Forensic Mass Spectrometry Deconvolution & AI Classification System** trained on the official **SWGDRUG Mass Spectral Library v3.14** ($N = 3,826$ reference spectra).

![Python](https://img.shields.io/badge/Python-3.10+-0284c7?style=flat&logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-ff4b4b?style=flat&logo=streamlit&logoColor=white)
![SWGDRUG](https://img.shields.io/badge/SWGDRUG-v3.14-16a34a?style=flat)
![Accreditation](https://img.shields.io/badge/ISO%2FIEC-17025-0f172a?style=flat)

---

## 🌟 Key Features

* **🧪 NNLS Multi-Component Mixture Deconvolution:**
  Uses Non-Negative Least Squares (`scipy.optimize.nnls`) to unmix complex multi-component street drug samples across 541 binned $m/z$ channels ($m/z$ 10–550).

* **📊 3-Panel Spectral Overlay & Residual Error Analysis ($e(m/z)$):**
  Renders interactive head-to-tail spectral comparisons displaying:
  1. Experimental Query Spectrum
  2. AI Reconstructed Composite Spectrum ($\hat{\mathbf{S}}_{\text{recon}}$)
  3. Residual Peak Difference Spectrum ($e(m/z) = I_{\text{exp}} - \hat{I}_{\text{recon}}$) to flag unmatched fragment ions and trace impurities.

* **🏷️ Functional Role Classification:**
  Categorizes deconvolved constituents into **Primary Active Substances**, **Inert Diluents / Excipients** (lactose, mannitol, sugars), **Pharmacological Adulterants** (caffeine, phenacetin, levamisole), and **Clandestine Synthesis Residuals**.

* **🎯 $R^2$ Goodness-of-Fit & Statistical Metrics:**
  Quantifies spectral unmixing quality using $R^2$ scores, Root Mean Square Error (RMSE), and Reverse Match Indexing (RMI).

* **🔗 Forensic Batch Profile Matching:**
  Compares deconvolved component ratios against cataloged seizure signatures to identify common-source regional supply chain batches.

* **🔥 Novel Formulation Synthesis & Synergistic Toxicity Intelligence:**
  Forward-synthesize test mixtures of Component A and Component B at custom ratios to evaluate **Synergistic Toxicity Hazard Scores (1–10)**, **Detector Masking Interference Indices**, and **Trafficking Profiles**.

---

## 🚀 Quick Start

### 1. Clone Repository
```bash
git clone https://github.com/Nyasa139/forensic-drug-analysis.git
cd forensic-drug-analysis
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Launch Streamlit Application
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## 📁 Repository Structure

```
forensic-drug-analysis/
├── app.py                   # Main Streamlit Web Application UI & Deconvolution Engine
├── parse_jcamp.py           # JCAMP-DX (SWGDRUG 3.14) Parsing & Mass Spectrum Binner
├── train_model.py           # Random Forest Classifier Training Pipeline
├── swgdrug_library.csv      # Metadata for 3,826 SWGDRUG Reference Compounds
├── swgdrug_features.csv     # Digitized 541 m/z Channel Mass Spectral Matrix
├── model.pkl                # Trained Random Forest Model Weights
├── features.pkl             # Feature Column Definitions (mz_10 to mz_550)
├── requirements.txt         # Project Dependencies
└── README.md                # Project Documentation
```

---

## 🔬 Scientific & Mathematical Methodology

1. **Mass Spec Feature Resampling:** Digitizes GC-MS spectra into 541 binned channels ($10 \le m/z \le 550$).
2. **Reverse Match Indexing ($R$-Fit):** Evaluates reference spectrum presence while discounting adulterant peaks.
3. **NNLS Spectral Unmixing:** Solves $\min_{\mathbf{c} \ge \mathbf{0}} \|\mathbf{S}_{\text{mix}} - \mathbf{M}\mathbf{c}\|_2^2$ to derive exact component content percentages.
4. **Random Forest Classification:** Ensembles 150 Decision Trees over unmixed spectra to output drug family classification probabilities.

---

## 📜 Standards & Compliance
Designed according to **SWGDRUG (Scientific Working Group for the Analysis of Seized Drugs)** analytical guidelines and **ISO/IEC 17025** forensic laboratory quality control standards.
