// Public frontend configuration for Nordic Atlas Live Agent Research.
// Safe to commit: Google OAuth Client IDs and Cloud Run URLs are public by design.
// All API secrets (GEMINI_API_KEY, GITHUB_TOKEN, SITE_VAULT_PASSPHRASE) and single-user
// email verification live exclusively on your Cloud Run backend.
window.NORDIC_ATLAS_CONFIG = {
  // Paste your deployed Cloud Run service URL here (no trailing slash), e.g.:
  // backendUrl: "https://nordic-atlas-agents-xxxx-uw.a.run.app",
  backendUrl: "",

  // Paste your Google OAuth 2.0 Web Client ID here, e.g.:
  // googleClientId: "1234567890-abcdefg.apps.googleusercontent.com",
  googleClientId: "",
};
