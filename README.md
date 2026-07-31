# Toulouse Fire Tracker

An English-language wildfire tracker for Toulouse and the Haute-Garonne department, France.

The headline feed rebuilds itself every 3 hours (06:00–21:00 Paris) via GitHub Actions.
The written "noon rundown" is updated by hand and carries its own date.

---

## One-time setup (about 15 minutes)

### 1. Create the repository

Go to github.com, click **New repository**.

- Name: `toulouse-fire-tracker`
- Visibility: **Public** (required for free GitHub Pages)
- Do not add a README — you already have one

### 2. Upload the files

On the empty repo page, click **uploading an existing file**. Drag in:

- `index.html`
- `build.py`
- `README.md`

The workflow file needs its folder structure, so add it separately:
click **Add file → Create new file**, and type this exact path in the name box:

```
.github/workflows/update.yml
```

Then paste in the contents of `update.yml` and commit.

### 3. Turn on GitHub Pages

**Settings → Pages → Source: Deploy from a branch → Branch: `main`, folder `/ (root)` → Save**

After a minute or two your page is live at:

```
https://YOUR-USERNAME.github.io/toulouse-fire-tracker/
```

That is the link you share. It never changes.

### 4. Allow the Action to commit

**Settings → Actions → General → Workflow permissions**
→ select **Read and write permissions** → Save.

Without this the daily build runs but cannot save its results.

### 5. Test it now

**Actions tab → "Update fire tracker" → Run workflow.**

It should finish green in under a minute, and the headlines section on your
page will fill in. If it fails, open the run and read the log — it prints
exactly which feed failed and why.

---

## Day-to-day use

- **Nothing to do.** It rebuilds daily at noon Paris time.
- **Force a refresh:** Actions tab → Run workflow.
- **Update the written rundown:** edit `index.html` directly on GitHub
  (pencil icon), add a new `rundown-entry` block above the previous one,
  and commit. Or ask me and I'll hand you the block to paste in.

## Things worth knowing

- **Clock change.** The cron is set for summer time (CEST). After late
  October, change `'0 10 * * *'` to `'0 11 * * *'` in `update.yml`.
- **GitHub's scheduler drifts.** Runs can be 5–30 minutes late at busy
  times. Not a problem here.
- **Inactivity pause.** GitHub disables scheduled Actions on repos with no
  commits for 60 days. It emails you first, and the daily commits keep it
  alive anyway.
- **The feed can come back empty.** If Google News changes something, the
  page says so plainly rather than showing stale headlines silently.
  The official map links always work regardless.

## Sources

Official maps linked on the page:

- Météo-France "Météo des forêts" — daily fire-danger by department
- EFFIS / Copernicus — EU satellite hotspot and burned-area mapping
- Préfecture de la Haute-Garonne — local orders and restrictions
- Sapeurs-pompiers — ground-level incident reports

Headline feed: Google News RSS, filtered to Haute-Garonne, Occitanie,
and France-wide wildfire coverage in French and English.

---

## Installing it as an app (PWA)

The page is also a progressive web app. Once deployed, anyone can install it
to their home screen — no app store, no account.

**iPhone (Safari only — this does not work in Chrome on iOS):**
open the link → Share button → *Add to Home Screen*

**Android (Chrome):**
open the link → ⋮ menu → *Install app* / *Add to Home screen*

It then opens full screen with its own icon, and still opens with no
signal — showing a red offline warning bar so nobody mistakes a saved
copy for live conditions.

### Extra files this needs

`manifest.json`, `sw.js`, and the four PNG icons must sit in the repo root
alongside `index.html`. Upload them the same way as the others.

### Important: HTTPS

Service workers only run over HTTPS. GitHub Pages provides this
automatically, so the deployed link works. Opening `index.html` as a local
file will *not* install — that is expected, not a bug.

---

## Live fire-danger level (optional)

The risk scale only shows a level if that level was confirmed **today**. If the
stored date is not today's date, the scale greys itself out and links to
Météo-France instead. It will never present an old level as current.

To have the level update automatically:

1. Register free at `portail-api.meteofrance.fr` and subscribe to the
   **Météo des forêts** API.
2. In the repo: **Settings → Secrets and variables → Actions → New repository
   secret**, named `METEOFRANCE_API_KEY`.
3. In `.github/workflows/update.yml`, add to the "Rebuild page" step:

   ```yaml
   - name: Rebuild page
     env:
       METEOFRANCE_API_KEY: ${{ secrets.METEOFRANCE_API_KEY }}
     run: python build.py
   ```

Without the key everything else still works — the page simply shows the level
as unconfirmed, which is the honest state.

**Note:** the response format is not verified in this repo. Check the Action log
after the first run; if it prints a parse failure, the field names in
`fetch_risk_level()` need adjusting to match the real payload.
