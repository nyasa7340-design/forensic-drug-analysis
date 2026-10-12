"""Reproducible synthetic signal experiments, independent of the blind library search."""
import numpy as np
from scipy.optimize import nnls
from analysis_core import MZ, normalize


def simulate_signals(spectra, percentages, noise=0.0, peak_loss=0.0, extra_ions=0, seed=42):
    spectra = np.asarray(spectra, dtype=float)
    fractions = np.asarray(percentages, dtype=float) / 100
    if spectra.ndim != 2 or spectra.shape[1] != 541 or len(fractions) != len(spectra):
        raise ValueError("Each selected reference must contain 541 mass channels.")
    if not np.isfinite(fractions).all() or (fractions < 0).any() or not np.isclose(fractions.sum(), 1):
        raise ValueError("Component signal weights must be nonnegative and sum to 100%.")
    if not 0 <= noise <= 20 or not 0 <= peak_loss <= 60 or not 0 <= extra_ions <= 8:
        raise ValueError("Experiment settings are outside their supported ranges.")
    normalized = np.stack([normalize(s) for s in spectra])
    contributions = normalized * fractions[:, None]
    factor = 100 / contributions.sum(axis=0).max()
    contributions *= factor
    clean = contributions.sum(axis=0)
    observed = clean.copy()
    rng = np.random.default_rng(int(seed))
    # Peak dropout uses a 1% base-peak threshold so rounding tails do not dominate.
    eligible = np.flatnonzero(clean >= 1)
    dropped = rng.choice(eligible, size=int(round(len(eligible) * peak_loss / 100)), replace=False)
    observed[dropped] = 0
    added = rng.choice(np.flatnonzero(clean == 0), size=min(int(extra_ions), int(np.count_nonzero(clean == 0))), replace=False)
    observed[added] += rng.uniform(5, 25, size=len(added))
    if noise:
        observed = np.maximum(0, observed + rng.normal(0, noise, 541))
    observed = normalize(observed)
    return {"clean": clean.tolist(), "observed": observed.tolist(), "contributions": contributions.tolist(),
            "settings": {"noise_std_base_peak_percent": float(noise), "peak_loss_percent": float(peak_loss),
                         "extra_ions_requested": int(extra_ions), "seed": int(seed)},
            "dropped_mz": MZ[dropped].astype(int).tolist(), "added_mz": MZ[added].astype(int).tolist(),
            "distortion_rmse": float(np.sqrt(np.mean((observed - clean) ** 2)))}


def fingerprint_diagnostics(spectra, names):
    spectra = np.stack([normalize(s) for s in spectra])
    norms = np.linalg.norm(spectra, axis=1)
    unit = spectra / norms[:, None]
    similarity = np.clip(unit @ unit.T, 0, 1)
    singular = np.linalg.svd(spectra.T, compute_uv=False)
    condition = float(singular[0] / singular[-1]) if singular[-1] > 1e-10 else None
    ions = []
    for i, name in enumerate(names):
        others = np.max(np.delete(spectra, i, axis=0), axis=0)
        contrast = spectra[i] - others
        selected_count = 0
        for position in np.argsort(-contrast, kind="stable"):
            if contrast[position] <= 0 or spectra[i, position] < 5:
                continue
            ions.append({"reference": str(name), "mz": int(MZ[position]), "reference_intensity": float(spectra[i, position]),
                         "largest_other_intensity": float(others[position]), "contrast": float(contrast[position])})
            selected_count += 1
            if selected_count == 5:
                break
    return {"similarities": similarity.tolist(), "condition_number": condition, "contrast_ions": ions}


def ratio_sweep(spectra, names, noise=0, peak_loss=0, extra_ions=0, seed=42):
    """Controlled A/B fitting with a disclosed two-reference basis; no library identification claim."""
    spectra = np.stack([normalize(s) for s in spectra[:2]])
    rows = []
    for percent in range(0, 101, 10):
        experiment = simulate_signals(spectra, [percent, 100-percent], noise, peak_loss, extra_ions, seed)
        observed = np.asarray(experiment['observed'])
        weights, _ = nnls(spectra.T, observed)
        recovered = weights / weights.sum() * 100 if weights.sum() else np.zeros(2)
        rows.append({"input_A_percent": percent, "recovered_A_percent": float(recovered[0]),
                     "recovered_B_percent": float(recovered[1]), "A_absolute_error_pp": float(abs(recovered[0]-percent)),
                     "fit_rmse": float(np.sqrt(np.mean((observed - spectra.T @ weights) ** 2)))})
    return rows
