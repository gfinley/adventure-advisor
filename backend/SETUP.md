# Live Agent Backend Setup (Google Cloud Run + AI Ultra Credits + Single-User Google Sign-In)

Follow these 5 steps (~5 minutes total) to connect the **"Spawn Research Agents"** prompt bar on https://gfinley.github.io/adventure-advisor/ to your Google AI Ultra credits with strict single-user Google Sign-In (`matthewgfinley@gmail.com` only) and automatic GitHub persistence.

---

## Step 1 — Claim Your Google AI Ultra Monthly Cloud / API Credits
1. Open **Google AI Studio**: https://aistudio.google.com (signed in as `matthewgfinley@gmail.com`).
2. Click **Claim free API credits** (or **Redeem credits**) in the left menu.
3. Link or create your Cloud Billing account (one-time \$5 prepay activation if new) and leave **Auto-apply future Google Developer Program credits** checked. Your AI Ultra monthly credit (\$40/mo on Ultra 5x or \$100/mo on Ultra 20x) now covers both your Gemini API calls **and** Cloud Run hosting.
4. Create/copy your **Gemini API key** (`GEMINI_API_KEY`) and note the **Google Cloud Project ID** (`GCP_PROJECT_ID`).

---

## Step 2 — Create Your Google Sign-In Web Client ID (Single-User Auth)
1. Open **Google Cloud Console → APIs & Services → Credentials** (in the same `GCP_PROJECT_ID`):
   https://console.cloud.google.com/apis/credentials
2. If prompted, configure the **OAuth consent screen** as **External** (or Testing with `matthewgfinley@gmail.com` as the sole test user).
3. Click **+ Create Credentials → OAuth client ID**:
   - **Application type:** `Web application`
   - **Name:** `Nordic Atlas Web`
   - **Authorized JavaScript origins:**
     - `https://gfinley.github.io`
     - `http://localhost:8080` *(optional, for local testing)*
4. Copy the **Client ID** (ends in `.apps.googleusercontent.com`) — this is your `GOOGLE_CLIENT_ID`. It is public by design; security is enforced server-side on Cloud Run by cryptographically verifying Google's signed ID token and checking `email == "matthewgfinley@gmail.com"`.

---

## Step 3 — Create a Scoped GitHub Token (Auto-Save to Repo)
1. Open https://github.com/settings/personal-access-tokens/new
2. **Token name:** `nordic-atlas-auto-save`
3. **Repository access:** **Only select repositories** → select `gfinley/adventure-advisor` ONLY.
4. **Permissions → Repository permissions → Contents:** **Read and write** (no other permissions needed).
5. Generate and copy the token (`GITHUB_TOKEN`).

---

## Step 4 — Deploy to Google Cloud Run (1 Command)
From Google Cloud Shell (https://shell.cloud.google.com) or your local terminal with `gcloud` installed:

```bash
git clone https://github.com/gfinley/adventure-advisor.git
cd adventure-advisor/backend
chmod +x deploy.sh

export GCP_PROJECT_ID="your-gcp-project-id"
export GOOGLE_CLIENT_ID="1234567890-xxxx.apps.googleusercontent.com"
export GEMINI_API_KEY="AIza..."
export GITHUB_TOKEN="github_pat_..."

./deploy.sh
```

> **Note:** `--allow-unauthenticated` at the Cloud Run network layer simply allows browser CORS preflight & requests to reach FastAPI; **every `/api/*` endpoint rejects any request without a valid Google Sign-In ID token belonging to `matthewgfinley@gmail.com` (`401`/`403`)** before any Gemini agent or GitHub call runs.
>
> To upgrade models later (e.g., to `gemini-4-hydrogen` or `gemini-4-neon`), set `GEMINI_RESEARCH_MODEL` and `GEMINI_SYNTH_MODEL` before re-running `./deploy.sh`.

---

## Step 5 — Connect the Web App
Either:
- **Permanent (recommended):** Paste your Cloud Run URL and `GOOGLE_CLIENT_ID` into [`config.js`](../config.js) in the repo root, commit, and push so every browser/device connects automatically; **or**
- **Instant test:** Click **Connect Backend** in the Nordic Atlas header and paste both values (saved in your browser's `localStorage`).

Now click **Sign in with Google**, type `"Iceland trip in May with drysuit scuba and cold solitude lodges"`, and watch the 3 parallel grounded Gemini agents research hotels, 4x4 rentals, flights, and operators live — and auto-commit the result straight to `gfinley/adventure-advisor`!
