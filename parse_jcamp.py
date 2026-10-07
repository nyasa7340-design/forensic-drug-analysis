import os
import re
import numpy as np
import pandas as pd

hpj_path = r"C:\Users\nyasa\Desktop\forensic-drug-analysis\JCAMP_01222025\SWGDRUG 314.HPJ"
output_dir = r"C:\Users\nyasa\Desktop\forensic-drug-analysis"

def categorize_compound(name):
    n = name.lower()
    
    # Cannabinoids
    if any(k in n for k in ['tetrahydrocannabinol', 'thc', 'cannabinol', 'cannabidiol', 'cbd', 'jwh', 'am-', 'xlr', 'pb-22', 'ur-144', 'hu-210', '5f-']):
        return 'Cannabinoid'
    
    # Opioids
    if any(k in n for k in ['fentanyl', 'heroin', 'morphine', 'codeine', 'oxycodone', 'hydrocodone', 'oxymorphone', 'hydromorphone', 'methadone', 'buprenorphine', 'tramadol', 'carfentanil', 'acetylfentanyl', 'furanylfentanyl', 'mitragynine', 'opiate', 'opioid', 'meperidine']):
        return 'Opioid'

    # Stimulants
    if any(k in n for k in ['amphetamine', 'methamphetamine', 'cocaine', 'cathinone', 'mdma', 'mda', 'mbdb', 'methylphenidate', 'ephedrine', 'pseudoephedrine', 'caffeine', 'mephedrone', 'pyrovalerone', 'mdpvalerone', 'mdpv', 'a-pvp', 'a-php', 'modafinil']):
        return 'Stimulant'

    # Depressants
    if any(k in n for k in ['zolpidem', 'alprazolam', 'diazepam', 'clonazepam', 'lorazepam', 'midazolam', 'oxazepam', 'temazepam', 'triazolam', 'etizolam', 'barbiturate', 'phenobarbital', 'secobarbital', 'butalbital', 'ghb', 'gbl', 'methaqualone', 'benzodiazepine']):
        return 'Depressant'

    # Hallucinogens
    if any(k in n for k in ['lsd', 'lysergic', 'psilocin', 'psilocybin', 'dmt', 'dimethyltryptamine', 'mescaline', 'ketamine', 'phencyclidine', 'pcp', '2c-b', '2c-i', '2c-e', 'nbome', 'salvinorin', 'tryptamine']):
        return 'Hallucinogen'

    # Anabolic Steroids
    if any(k in n for k in ['androsterone', 'testosterone', 'nandrolone', 'stanozolol', 'boldenone', 'trenbolone', 'methandrostenolone', 'oxandrolone', 'oxymetholone', 'masteron', 'dromostanolone', 'epitestosterone', 'dehydroepiandrosterone', 'dhea']):
        return 'Anabolic Steroid'

    # Precursors / Cutting Agents / Other
    return 'Precursor / Other'

entries = []
current_entry = {}
in_xydata = False

print("Parsing SWGDRUG 314.HPJ file...")
with open(hpj_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        line_str = line.strip()
        if line_str.startswith("##TITLE="):
            if current_entry and "name" in current_entry:
                entries.append(current_entry)
            current_entry = {"title": line_str.split("=", 1)[1].strip(), "peaks": {}}
            in_xydata = False
        elif line_str.startswith("##CAS NAME="):
            current_entry["name"] = line_str.split("=", 1)[1].strip()
        elif line_str.startswith("##NAMES="):
            current_entry["swgdrug_id"] = line_str.split("=", 1)[1].strip()
        elif line_str.startswith("##MW="):
            try:
                current_entry["mw"] = float(line_str.split("=", 1)[1].strip())
            except:
                current_entry["mw"] = 0.0
        elif line_str.startswith("##MOLFORM="):
            current_entry["formula"] = line_str.split("=", 1)[1].strip()
        elif line_str.startswith("##XYDATA="):
            in_xydata = True
        elif line_str.startswith("##END="):
            in_xydata = False
        elif in_xydata:
            if line_str.startswith("##"):
                in_xydata = False
            else:
                parts = line_str.split()
                if len(parts) >= 2:
                    try:
                        mz = int(round(float(parts[0])))
                        intensity = float(parts[1])
                        if 10 <= mz <= 550:
                            current_entry["peaks"][mz] = max(current_entry["peaks"].get(mz, 0), intensity)
                    except ValueError:
                        pass

if current_entry and "name" in current_entry:
    entries.append(current_entry)

print(f"Parsed {len(entries)} entries successfully.")

# Prepare feature columns (m/z 10 to 550)
mz_cols = [f"mz_{i}" for i in range(10, 551)]

library_records = []
feature_rows = []

for idx, e in enumerate(entries):
    c_name = e.get("name", f"Compound_{idx+1}")
    sw_id = e.get("swgdrug_id", f"SWG_{idx+1}")
    mw = e.get("mw", 0.0)
    formula = e.get("formula", "Unknown")
    category = categorize_compound(c_name)
    
    # Peak vector
    peaks = e.get("peaks", {})
    max_val = max(peaks.values()) if peaks and max(peaks.values()) > 0 else 1.0
    
    # Find base peak m/z
    base_mz = max(peaks, key=peaks.get) if peaks else 0
    
    row_vec = np.zeros(len(mz_cols), dtype=np.float32)
    for mz, val in peaks.items():
        if 10 <= mz <= 550:
            row_vec[mz - 10] = round((val / max_val) * 100.0, 2)
            
    library_records.append({
        'id': idx + 1,
        'swgdrug_id': sw_id,
        'name': c_name,
        'category': category,
        'formula': formula,
        'mw': mw,
        'base_peak_mz': base_mz,
        'num_peaks': len(peaks)
    })
    
    feature_rows.append(row_vec)

df_lib = pd.DataFrame(library_records)
df_feat = pd.DataFrame(feature_rows, columns=mz_cols)

# Combine library & features for training CSV
df_feat_with_target = df_feat.copy()
df_feat_with_target['Category'] = df_lib['category']
df_feat_with_target['Name'] = df_lib['name']
df_feat_with_target['SWGDRUG_ID'] = df_lib['swgdrug_id']
df_feat_with_target['MW'] = df_lib['mw']

df_lib.to_csv(os.path.join(output_dir, "swgdrug_library.csv"), index=False)
df_feat_with_target.to_csv(os.path.join(output_dir, "swgdrug_features.csv"), index=False)

print(f"Saved swgdrug_library.csv ({len(df_lib)} rows) and swgdrug_features.csv ({df_feat_with_target.shape})")
