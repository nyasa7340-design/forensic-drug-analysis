import json
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from analysis_core import MZ
from simulation_core import simulate_signals, fingerprint_diagnostics, ratio_sweep


def render_simulator(library, matrix, execute, render_report):
    st.markdown('<div class="eyebrow">SIMULATION WORKSPACE</div>', unsafe_allow_html=True)
    st.subheader("Mixture experiments")
    st.caption("Compare signal contributions and test recovery under controlled measurement conditions.")
    builder, challenge, sweep_tab = st.tabs(["Signal canvas", "Blind recovery challenge", "Ratio sweep"])
    options = list(range(len(library)))

    def label(i):
        row = library.iloc[i]
        return f"{row['name']} · #{row.id} · {row.formula}"

    with builder:
        with st.container(border=True):
            st.markdown("**Reference signals**")
            a, b = st.columns(2)
            first = a.selectbox("Reference A", options, format_func=label, index=1746, key="studio_A")
            second = b.selectbox("Reference B", options, format_func=label, index=1109, key="studio_B")
            enable_third = st.checkbox("Add a third reference signal", key="studio_third_enabled")
            third = st.selectbox("Reference C", options, format_func=label, index=1835, key="studio_C") if enable_third else None
            share_a = st.slider("Reference A · relative coefficient (%)", 0, 100, 70, key="studio_share_A")
            share_c = st.slider("Reference C · relative coefficient (%)", 0, 100-share_a, min(10, 100-share_a), key="studio_share_C") if enable_third and share_a < 100 else 0
            shares = [share_a, 100-share_a-share_c] + ([share_c] if enable_third else [])
            indices = [first, second] + ([third] if enable_third else [])
            names = [str(library.iloc[i]['name']) for i in indices]
            spectra = matrix[indices]
            for col, name, share in zip(st.columns(len(names)), names, shares):
                col.metric(name, f"{share}%", help="Coefficient of a normalized reference signal; not concentration.")
        with st.container(border=True):
            st.markdown("**Measurement conditions**")
            a, b, c, d = st.columns(4)
            noise = a.slider("Noise · intensity SD", 0.0, 20.0, 0.0, step=0.5, key="studio_noise", help="Gaussian noise in base-peak intensity units, added to all bins; negative intensities are clipped to zero.")
            loss = b.slider("Missing peaks (%)", 0, 60, 0, key="studio_loss", help="Randomly remove this fraction of clean peaks with intensity at least 1 before adding noise.")
            extra = c.slider("Unmodelled ions", 0, 8, 0, key="studio_extra", help="Add random ions at initially empty bins, with intensities of 5–25 before final normalization.")
            seed = int(d.number_input("Experiment seed", 0, 999999, 42, key="studio_seed"))
            st.caption("Signal weights sum to 100%. Changing a seed changes the artificial disturbances; repeating the same settings reproduces the spectrum.")
        experiment = simulate_signals(spectra, shares, noise, loss, extra, seed)
        diagnostics = fingerprint_diagnostics(spectra, names)
        st.markdown("**Live signal canvas**")
        view = st.radio("Canvas view", ["Component contributions", "Clean vs challenged"], horizontal=True, key="studio_canvas_view")
        fig, ax = plt.subplots(figsize=(12, 3.4))
        if view == "Component contributions":
            bottom = np.zeros(541)
            for name, values, color in zip(names, experiment['contributions'], ['#137780', '#4669be', '#cf7955']):
                values = np.asarray(values)
                ax.bar(MZ, values, bottom=bottom, width=.85, color=color, label=name)
                bottom += values
            ax.set_title("Where each reference contributes to the clean mixture", loc='left', fontsize=10)
        else:
            ax.vlines(MZ, 0, experiment['clean'], color='#137780', label='Clean signal', lw=1.2)
            ax.vlines(MZ, 0, -np.asarray(experiment['observed']), color='#cf7955', label='Challenged signal · mirrored', lw=1)
            ax.axhline(0, color='#8c9aab', lw=.7)
        ax.set_xlabel("m/z")
        ax.set_ylabel("Relative intensity")
        ax.legend(fontsize=8, loc='upper right')
        ax.spines[['top','right']].set_visible(False)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
        a, b, c = st.columns(3)
        a.metric("Challenge distortion · RMSE", f"{experiment['distortion_rmse']:.2f}")
        b.metric("Peaks removed", len(experiment['dropped_mz']))
        c.metric("Extra ions added", len(experiment['added_mz']))
        with st.expander("Fingerprint overlap & distinguishing ions", expanded=True):
            frame = pd.DataFrame(diagnostics['similarities'], index=names, columns=names)
            st.dataframe(frame.style.format('{:.4f}').background_gradient(cmap='Blues', vmin=0, vmax=1), width='stretch')
            condition = diagnostics['condition_number']
            if condition is None:
                st.warning("These fingerprints are linearly dependent. Their individual coefficients cannot be uniquely recovered.")
            else:
                st.caption(f"Basis condition number: {condition:.2f}. Larger values indicate greater sensitivity to measurement changes; this is not a validated identification score.")
            ions = pd.DataFrame(diagnostics['contrast_ions'])
            if ions.empty:
                st.info("No distinguishing ions meet the chosen contrast criteria.")
            else:
                st.dataframe(ions, hide_index=True, width='stretch')
                st.caption("Up to five ions per reference with intensity ≥5 and positive contrast against the strongest other selected reference. These are relative to this selected set, not unique across the full library.")
        with st.expander("Inspect challenge settings and altered channels"):
            st.json({**experiment['settings'], 'dropped_mz': experiment['dropped_mz'], 'added_mz': experiment['added_mz']})
        st.download_button("Download experiment blueprint", json.dumps({'references': [{'entry_id': int(library.iloc[i].id), 'name': n, 'input_coefficient_percent': s} for i,n,s in zip(indices,names,shares)], **experiment}, indent=2), "mixture-blueprint.json", "application/json", key="studio_blueprint")

    with challenge:
        st.markdown("**Full-library recovery test**")
        st.write("The analyzer receives only the challenged spectrum. The selected reference IDs and coefficients are withheld from candidate selection and fitting.")
        st.caption("Uses the current Signal canvas settings. The known inputs are used only afterward to score recovery.")
        if st.button("Simulate and analyze", type="primary", key="studio_run"):
            if len(set(indices)) != len(indices):
                st.error("Choose different entries for each reference signal.")
            else:
                truth = [{'entry_id': int(library.iloc[i].id), 'name': n, 'input_coefficient_percent': s} for i,n,s in zip(indices,names,shares)]
                bundle = {'experiment': experiment, 'fingerprint_diagnostics': diagnostics}
                report = execute(experiment['observed'], 'Synthetic challenge: ' + ' + '.join(f'{s}% {n}' for s,n in zip(shares,names)), "Synthetic signal mixture", truth, simulation_settings=bundle)
                st.session_state.simulation_report = report
        if 'simulation_report' in st.session_state:
            report = st.session_state.simulation_report
            truth = report['simulation']
            fitted = {c['entry_id']: c['fit_weight_percent'] for c in report['components']}
            comparison = pd.DataFrame(truth)
            comparison['recovered_fit_weight_percent'] = comparison.entry_id.map(fitted).fillna(0)
            comparison['absolute_error_pp'] = abs(comparison.input_coefficient_percent-comparison.recovered_fit_weight_percent)
            selected_ids = set(comparison.entry_id)
            off_target = sum(c['fit_weight_percent'] for c in report['components'] if c['entry_id'] not in selected_ids)
            a, b, c = st.columns(3)
            a.metric("Mean coefficient error", f"{comparison.absolute_error_pp.mean():.2f} pp")
            b.metric("Weight assigned elsewhere", f"{off_target:.2f}%")
            active_inputs = comparison[comparison.input_coefficient_percent > 0]
            recovered_count = sum(row.entry_id in fitted for row in active_inputs.itertuples())
            c.metric("Input entries in fitted set", f"{recovered_count}/{len(active_inputs)}")
            st.dataframe(comparison, hide_index=True, width='stretch')
            st.caption("pp = percentage points. Scores apply to the saved experiment below, not unsaved control changes. Exact entry scoring may penalize spectrally indistinguishable alternatives; inspect alternative IDs in the fit table.")
            settings = report.get('simulation_settings', {}).get('experiment', {}).get('settings')
            if settings:
                st.caption(f"Saved challenge · seed {settings['seed']} · noise SD {settings['noise_std_base_peak_percent']:g} · peak loss {settings['peak_loss_percent']:g}% · requested extra ions {settings['extra_ions_requested']}")
            render_report(report, 'simulation')
        else:
            st.info("Create a blind recovery challenge to compare known inputs with the library-derived fit.")

    with sweep_tab:
        st.markdown("**Coefficient recovery across mixing ratios**")
        st.write("Sweep reference A from 0% to 100% in eleven steps. Apply the current noise, missing-peak, extra-ion, and seed settings at every step.")
        st.info("This is a controlled fit using only references A and B. It measures recovery when the reference identities are known, separately from the full-library blind challenge. Reference C is excluded from this experiment.")
        if st.button("Run 11-step ratio sweep", type="primary", key="studio_sweep_run"):
            if first == second:
                st.error("Choose different entries for references A and B.")
            else:
                rows = ratio_sweep(matrix[[first,second]], names[:2], noise, loss, extra, seed)
                st.session_state.studio_sweep = {'rows': rows, 'references': names[:2], 'settings': experiment['settings'],
                                               'entry_ids': [int(library.iloc[i].id) for i in [first,second]]}
        if 'studio_sweep' in st.session_state:
            stored = st.session_state.studio_sweep
            rows = pd.DataFrame(stored['rows'])
            st.caption(f"Saved sweep · A: {stored['references'][0]} · B: {stored['references'][1]} · seed {stored['settings']['seed']} · noise {stored['settings']['noise_std_base_peak_percent']:g} · peak loss {stored['settings']['peak_loss_percent']:g}%")
            fig, axes = plt.subplots(1, 2, figsize=(12, 3.5))
            axes[0].plot(rows.input_A_percent, rows.input_A_percent, '--', color='#93a4b7', label='Ideal recovery')
            axes[0].plot(rows.input_A_percent, rows.recovered_A_percent, 'o-', color='#137780', label='Recovered A')
            axes[0].set_ylabel('Recovered A coefficient (%)')
            axes[1].plot(rows.input_A_percent, rows.A_absolute_error_pp, 'o-', color='#cf7955')
            axes[1].set_ylabel('A coefficient error (percentage points)')
            for ax in axes:
                ax.set_xlabel('Input A coefficient (%)')
                ax.grid(alpha=.15)
                ax.spines[['top','right']].set_visible(False)
            axes[0].legend(fontsize=8)
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
            st.dataframe(rows, hide_index=True, width='stretch')
            st.download_button("Download sweep data", rows.to_csv(index=False), "ratio-sweep.csv", "text/csv", key="studio_sweep_csv")
            st.download_button("Download sweep with settings", json.dumps(stored, indent=2), "ratio-sweep.json", "application/json", key="studio_sweep_json")
            st.caption("Eleven synthetic trials with one seed are exploratory, not a limit of detection, confidence interval, or validated performance study.")
