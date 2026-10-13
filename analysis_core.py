"""Validated nominal-mass spectrum parsing and reproducible library fitting."""
from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd
from scipy.optimize import nnls

MZ = np.arange(10, 551)
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
PAIR = re.compile(rf"^\s*({NUMBER})\s*(?::|,|;|\s)\s*({NUMBER})\s*$")


@dataclass
class Spectrum:
    name: str
    vector: np.ndarray
    peak_count: int
    excluded_peak_count: int = 0


def normalize(vector):
    vector = np.asarray(vector, dtype=float).reshape(-1)
    if vector.shape != (len(MZ),) or not np.isfinite(vector).all():
        raise ValueError("A spectrum must contain 541 finite intensity values.")
    if (vector < 0).any() or vector.max() <= 0:
        raise ValueError("Intensities must be nonnegative, with at least one positive peak.")
    return vector / vector.max() * 100.0


def from_pairs(pairs, name):
    vector = np.zeros(len(MZ))
    for mass, intensity in pairs:
        if not np.isfinite([mass, intensity]).all() or intensity < 0:
            raise ValueError("Peak values must be finite and intensities cannot be negative.")
        # Nominal-mass bins: half-integer values round upward consistently.
        channel = int(np.floor(mass + 0.5))
        if not 10 <= mass <= 550:
            raise ValueError(f"m/z {mass:g} lies outside the supported range 10–550.")
        vector[channel - 10] += intensity
    return Spectrum(name, normalize(vector), int(np.count_nonzero(vector)))


def parse_spectra(content, name="Uploaded spectrum"):
    """Accept strict peak lists/CSV and uncompressed JCAMP XY pairs; keep records separate."""
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Use a UTF-8 text spectrum file.") from exc
    if len(content) > 20_000_000:
        raise ValueError("Files must be smaller than 20 MB.")
    is_jcamp = "##" in content
    if not is_jcamp:
        pairs = []
        # Colon notation supports comma-separated pairs on one line.
        lines = content.replace(",", "\n").splitlines() if ":" in content else content.splitlines()
        for number, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith(("#", "$$")):
                continue
            if not pairs and re.fullmatch(r"(?i)m/?z\s*[,;\t ]\s*(?:relative[_ ]?)?intensity", line):
                continue
            match = PAIR.fullmatch(line)
            if not match:
                raise ValueError(f"Invalid peak on line {number}. Use m/z,intensity or m/z:intensity.")
            pairs.append(tuple(map(float, match.groups())))
        return [from_pairs(pairs, name)]
    records, pairs, title, active, xfactor, yfactor, expected = [], [], name, False, 1.0, 1.0, None

    def finish():
        if pairs:
            if expected is not None and len(pairs) != expected:
                raise ValueError(f"{title}: NPOINTS declares {expected} peaks but {len(pairs)} were read.")
            scaled = [(x * xfactor, y * yfactor) for x, y in pairs]
            if any(not np.isfinite([x, y]).all() or y < 0 for x, y in scaled):
                raise ValueError(f"{title}: peaks must be finite and intensities nonnegative.")
            supported = [(x, y) for x, y in scaled if 10 <= x <= 550]
            record = from_pairs(supported, title)
            record.excluded_peak_count = len(scaled) - len(supported)
            records.append(record)

    for number, line in enumerate(content.splitlines(), 1):
        line = line.split("$$", 1)[0].strip()
        if not line:
            continue
        if line.startswith("##"):
            key, _, value = line[2:].partition("=")
            key, value = key.strip().upper(), value.strip()
            if key == "TITLE":
                finish()
                pairs, title, xfactor, yfactor, expected = [], value or name, 1.0, 1.0, None
            elif key == "CAS NAME":
                title = value or title
            elif key in ("XFACTOR", "YFACTOR"):
                try:
                    factor = float(value)
                    if not np.isfinite(factor) or factor <= 0:
                        raise ValueError()
                    if key == "XFACTOR":
                        xfactor = factor
                    else:
                        yfactor = factor
                except ValueError as exc:
                    raise ValueError(f"Invalid {key}.") from exc
            elif key == "NPOINTS":
                try:
                    expected = int(value)
                except ValueError as exc:
                    raise ValueError("Invalid NPOINTS.") from exc
            elif key in ("XYDATA", "PEAK TABLE", "PEAKTABLE"):
                compact = value.upper().replace(" ", "")
                if compact not in ("(XY..XY)", "(XY..XY)..", "(X,Y)"):
                    raise ValueError("Compressed JCAMP data is unsupported. Export an uncompressed (XY..XY) peak table or CSV.")
                active = True
                continue
            active = False
        elif active:
            tokens = re.split(r"[\s,;]+", line)
            if len(tokens) % 2 or any(not re.fullmatch(NUMBER, t) for t in tokens):
                raise ValueError(f"Invalid or compressed JCAMP peak data on line {number}.")
            pairs.extend((float(tokens[i]), float(tokens[i + 1])) for i in range(0, len(tokens), 2))
    finish()
    if not records:
        raise ValueError("No supported peak table found in this file.")
    return records


def load_library(directory):
    directory = Path(directory)
    metadata = pd.read_csv(directory / "swgdrug_library.csv").fillna("")
    features = pd.read_csv(directory / "swgdrug_features.csv")
    columns = [f"mz_{mass}" for mass in MZ]
    if len(metadata) != len(features) or not len(metadata):
        raise ValueError("Library metadata and spectra have different row counts.")
    for meta_col, feature_col in [("name", "Name"), ("swgdrug_id", "SWGDRUG_ID")]:
        if not metadata[meta_col].astype(str).equals(features[feature_col].astype(str)):
            raise ValueError("Library metadata is not aligned with its spectral rows.")
    matrix = features[columns].to_numpy(dtype=float)
    if not np.isfinite(matrix).all() or (matrix < 0).any() or (matrix.max(axis=1) <= 0).any():
        raise ValueError("Library contains invalid or empty spectra.")
    matrix = matrix / matrix.max(axis=1, keepdims=True) * 100
    return metadata, matrix


def analyze(vector, metadata, matrix, candidate_limit=60, exclude_entry_ids=None):
    """Compare a spectrum with the library, optionally withholding known references."""
    if exclude_entry_ids:
        excluded = {int(entry_id) for entry_id in exclude_entry_ids}
        keep = ~metadata["id"].astype(int).isin(excluded).to_numpy()
        metadata = metadata.loc[keep].reset_index(drop=True)
        matrix = matrix[keep]
        if not len(matrix):
            raise ValueError("At least one library reference must remain for comparison.")
    query = normalize(vector)
    norms = np.linalg.norm(matrix, axis=1)
    units = matrix / norms[:, None]
    similarities = np.clip(units @ (query / np.linalg.norm(query)), 0, 1)
    ranking = np.argsort(-similarities, kind="stable")
    exact = ranking[similarities[ranking] >= 1 - 1e-10]
    candidates = list(ranking[:min(candidate_limit, len(matrix))])
    # Include candidates found against positive unexplained peaks to recover weaker signals.
    for _ in range(3):
        # Exact duplicate spectra cannot be separated; retain a stable representative.
        _, unique_positions = np.unique(matrix[candidates], axis=0, return_index=True)
        candidates = [candidates[i] for i in sorted(unique_positions)]
        basis = matrix[candidates].T
        weights, _ = nnls(basis, query, maxiter=10 * len(candidates))
        reconstructed = basis @ weights
        residual = query - reconstructed
        positive = np.maximum(residual, 0)
        if np.linalg.norm(positive) < 1e-7:
            break
        extra = np.argsort(-(units @ positive), kind="stable")[:20]
        added = [int(i) for i in extra if int(i) not in candidates]
        if not added:
            break
        candidates.extend(added)
    # Refit after the final candidate expansion.
    _, unique_positions = np.unique(matrix[candidates], axis=0, return_index=True)
    candidates = [candidates[i] for i in sorted(unique_positions)]
    basis = matrix[candidates].T
    weights, _ = nnls(basis, query, maxiter=10 * len(candidates))
    reconstructed = basis @ weights
    residual = query - reconstructed
    sse = float(residual @ residual)
    sst = float(np.sum((query - query.mean()) ** 2))
    total = weights.sum()
    components = []
    for position in np.argsort(-weights, kind="stable"):
        if weights[position] <= 1e-8:
            continue
        index = candidates[position]
        identical = np.flatnonzero(np.all(np.isclose(matrix, matrix[index], atol=1e-8, rtol=0), axis=1))
        components.append({"entry_id": int(metadata.iloc[index]["id"]), "name": str(metadata.iloc[index]["name"]),
                           "coefficient": float(weights[position]), "fit_weight_percent": float(weights[position] / total * 100),
                           "indistinguishable_entry_ids": metadata.iloc[identical]["id"].astype(int).tolist()})
    best = int(ranking[0])
    # Thresholds are transparent screening heuristics, never claims of identity/purity.
    status = "Exact spectral match" if len(exact) else ("Tentative library match" if similarities[best] >= .85 else "Inconclusive library match")
    return {"status": status, "best_entry_id": int(metadata.iloc[best]["id"]),
            "best_name": str(metadata.iloc[best]["name"]), "cosine_similarity": float(similarities[best]),
            "r_squared": 1 - sse / sst if sst > 0 else None,
            "rmse": float(np.sqrt(sse / len(query))), "relative_residual": float(np.linalg.norm(residual) / np.linalg.norm(query)),
            "peak_count": int(np.count_nonzero(query)), "exact_match_entry_ids": metadata.iloc[exact]["id"].astype(int).tolist(),
            "matches": [{"entry_id": int(metadata.iloc[i]["id"]), "name": str(metadata.iloc[i]["name"]),
                         "formula": str(metadata.iloc[i]["formula"]), "mw": float(metadata.iloc[i]["mw"]),
                         "cosine_similarity": float(similarities[i])} for i in ranking[:10]],
            "components": components, "query": query.tolist(), "reconstructed": reconstructed.tolist(), "residual": residual.tolist(),
            "candidate_count": len(candidates)}
