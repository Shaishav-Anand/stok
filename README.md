# STOK — Deploy to Render

## Step 1 — Push to GitHub

You need the code in a GitHub repo. Do this on your computer:

```bash
# Install git if you don't have it: https://git-scm.com
cd stok
git init
git add .
git commit -m "Initial commit"
```

Then:
1. Go to https://github.com/new
2. Create a new repo called `stok` (set to Private)
3. Copy the commands GitHub shows you under "push existing repo":

```bash
git remote add origin https://github.com/YOUR_USERNAME/stok.git
git branch -M main
git push -u origin main
```

---

## Step 2 — Create Render Account

Go to https://render.com and sign up (free, no credit card needed).

---

## Step 3 — Deploy with Blueprint (easiest)

1. In Render dashboard, click **New → Blueprint**
2. Connect your GitHub account when prompted
3. Select your `stok` repo
4. Render reads `render.yaml` automatically and shows you:
   - `stok-inventory` (web service)
   - `stok-db` (PostgreSQL database)
5. Click **Apply** — Render builds and deploys both

Wait ~3-5 minutes for the first build to complete.

---

## Step 4 — Create your account

Once deployed, Render gives you a URL like:
`https://stok-inventory.onrender.com`

Open that URL + `/docs` to access the API:
`https://stok-inventory.onrender.com/docs`

Click **POST /auth/register**, then **Try it out**:
```json
{
  "email": "you@company.com",
  "password": "yourpassword"
}
```
Add `?name=YourName` to the URL field. Click Execute.

---

## Step 5 — Sign in and upload data

1. Open `https://stok-inventory.onrender.com`
2. Sign in with the account you just created
3. Go to **Upload CSV** tab
4. Upload in this order:
   - `sample_data/suppliers.csv`
   - `sample_data/skus.csv`
   - `sample_data/inventory.csv`
   - `sample_data/sales.csv`
5. Go to Dashboard → click **Run AI Agent**
6. Pending actions will appear — approve or reject them

---

## Free Tier Limitations

| Limitation | Detail |
|------------|--------|
| Sleep after inactivity | App pings itself every 10min to stay awake |
| First request after sleep | ~30 seconds (if ping missed) |
| PostgreSQL expires | After 90 days — export data and recreate |
| Build minutes | 500/month (plenty for one app) |

### When PostgreSQL expires (after 90 days):
1. Go to Render dashboard → your database → **Backups** → download
2. Delete the old database service
3. Create a new free PostgreSQL on Render
4. Update `DATABASE_URL` in your web service environment variables
5. Restore the backup

---

## Updating the app

After making code changes locally:

```bash
git add .
git commit -m "describe your change"
git push
```

Render auto-deploys on every push to `main`.

---

## View logs

Render dashboard → `stok-inventory` → **Logs** tab

Useful for:
- Seeing agent scan output
- Debugging upload errors
- Checking keep-alive pings

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Build fails | Check Logs tab — usually a missing package |
| "Application error" on load | Check Logs — likely DB connection issue |
| Slow first load | Normal — free tier waking up, wait 30s |
| CSV upload fails | Make sure you uploaded SKUs before Sales |
| Login doesn't work | Re-run POST /auth/register via /docs |
| No actions after agent run | Upload inventory + sales CSVs first |
