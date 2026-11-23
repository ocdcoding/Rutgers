# Run the Rutgers notifier on GitHub (free, no laptop needed)

About 10 minutes, all in your browser.

## 1. Make the repo
1. Sign in at github.com (create a free account if you don't have one).
2. Click **+ → New repository**. Name it `rutgers-notifier`, choose **Public**, and click **Create repository**.
   Public matters: public repos get unlimited free Actions minutes. Only your index numbers are visible;
   your webhook stays hidden (step 3).

## 2. Upload the files
1. In the new repo, click **uploading an existing file** and drag in `check_once.py` and `config.json`.
   Click **Commit changes**.
2. Click **Add file → Create new file** and type this exact name: `.github/workflows/check.yml`
   Paste in everything from `check.yml`, then click **Commit changes**.

## 3. Add your Discord webhook as a secret
**Settings → Secrets and variables → Actions → New repository secret**
- Name: `DISCORD_WEBHOOK`
- Secret: your webhook URL (Discord channel → Edit Channel → Integrations → Webhooks → Copy URL)

## 4. Set your classes
Open `config.json` in the repo, click the pencil icon, put your 5-digit index numbers in `"indexes"`,
and commit. Spring 2027 is `"year": 2027, "term": 1`. Fall is term 9, Summer 7, Winter 0.

## 5. Turn it on and test it
**Actions** tab → **Check Rutgers sections** → **Run workflow**. It should finish with a green check.
After that it runs by itself about every 5 minutes. GitHub sometimes delays scheduled runs to 10–15
minutes when it's busy.

Tip: to test the Discord alert, temporarily add an index you know is open.

## Good to know
- You only get pinged when a section changes from closed to open, not every 5 minutes.
- To change classes later, just edit `config.json`.
- To stop it: Actions tab → Check Rutgers sections → "..." → **Disable workflow**.
- GitHub pauses scheduled jobs on repos with no activity for 60 days. If that happens, re-enable it
  in the Actions tab.
