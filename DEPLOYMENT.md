# Deploy the frontend on Vercel and the backend on Render

The current website does not need Streamlit. Vercel serves only `frontend/`.
Render runs the Python API and stores history, notebooks, and evidence files on
a persistent disk. Uploads and downloads go directly to Render.

## 1. Put the project in GitHub

Commit and push this project to your own GitHub repository. Do not upload
`__pycache__/`, which contains local records. Existing records are not migrated
by deployment.

## 2. Create the Render backend

In Render, choose **New > Blueprint**, connect the repository, and use the
included `render.yaml`. Review the paid service and disk pricing before creating
it. The configuration selects a 2 GB service for the scientific calculations
and a 1 GB persistent disk. A free service does not provide this persistent disk.

When prompted for `FORENSIC_ALLOWED_ORIGINS`, initially enter
`https://example.invalid`. Replace this after Vercel gives you the real domain.
Do not use a wildcard.

The Blueprint sets:

- Build: `pip install -r requirements.txt`
- Start: `python server.py --host 0.0.0.0`
- Port: Render's `PORT` environment variable, read automatically
- Health check: `/api/status`
- Persistent storage: `FORENSIC_STORAGE_DIR=/var/data/forensic`

Copy the actual Render service URL. Open `<RENDER_URL>/api/status` and confirm
that the JSON reports 3826 reference spectra.

## 3. Configure the frontend

Edit `frontend/js/config.js`:

```js
export const API_BASE_URL = 'https://YOUR-ACTUAL-SERVICE.onrender.com';
```

Use the actual URL copied from Render, without an `/api` suffix. Commit and push.
This URL is public configuration, not a password. For local same-server use,
leave the value empty instead.

## 4. Create the Vercel frontend

Import the same GitHub repository into Vercel with:

- Root Directory: `frontend`
- Framework Preset: Other
- Build Command: empty (no build step)
- Output Directory: `.`

`frontend/vercel.json` supplies the static-site settings. The root-level Python
Vercel files are legacy and are not used with this Root Directory. Do not choose
the repository root, or Vercel may attempt to package the Python backend.

Deploy and copy the production website origin, for example
`https://your-project.vercel.app`.

## 5. Allow the frontend on Render

In the Render service's Environment settings, set `FORENSIC_ALLOWED_ORIGINS` to
the exact Vercel origin. Include `https://`, with no path or trailing slash.
Save and redeploy/restart the service. For multiple approved domains, separate
them with commas. Preview deployment domains require their own exact entry.

## 6. Check the deployed website

1. Overview shows `3,826 reference spectra · Ready`.
2. Paste `82:100, 182:75` into Analysis and save a result.
3. Download its CSV and JSON reports.
4. Create a notebook, link the result, attach a sample file, and export the ZIP.
5. Restart the Render service and confirm the history and notebook remain.

The sample files in `sample_inputs/` can be used for upload checks. Render also
serves the complete website at its own URL, which can help diagnose frontend
configuration problems.

## Local checks

```powershell
python -m unittest test_frontend_api -v
node --test frontend/js/components.test.js frontend/js/api.test.js
python server.py --port 8503
```

## Shared records and access

This version has no user login or per-user data separation: everyone who can
reach the backend can access the same records. CORS controls browser origins;
it does not authenticate users or block direct API clients. Use demonstration
data for this deployment. Private evidence requires authentication and access
controls before upload. Keep the service on one instance with its attached disk
and plan backups for records you need to retain.

References: https://render.com/docs/blueprint-spec and https://render.com/docs/disks
