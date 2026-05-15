// Sets window.EWASH_API_BASE for the PWA. Resolved in order:
//   1. ?api=<url> query param (dev only — handy when pointing the PWA at a
//      local FastAPI on http://localhost:8000 or an ngrok tunnel).
//   2. The compile-time constant below (production default).
//
// Loaded as plain <script src> in index.html BEFORE the JSX bundles, so
// api.js and app.jsx can read window.EWASH_API_BASE synchronously without
// waiting for Babel.
(function () {
  const params = new URLSearchParams(location.search);
  const override = params.get("api");
  // TODO(omar): confirm prod URL once Railway domain is finalized.
  const prodDefault = "https://ewash-agent-production.up.railway.app";
  window.EWASH_API_BASE = override || prodDefault;
  if (override) {
    console.info("[ewash] API base overridden via ?api=", override);
  }
})();
