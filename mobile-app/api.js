(function () {
  const BOOKINGS_STORAGE_KEY = ["ewash.bookings", "token"].join("_");
  const PHONE_STORAGE_KEY = "ewash.phone";
  const DEFAULT_TIMEOUT_MS = 10000;
  const LOG_RING_LIMIT = 200;

  function _makeSessionId() {
    const cryptoObj = window.crypto || window.msCrypto;
    if (cryptoObj && cryptoObj.getRandomValues) {
      const bytes = new Uint8Array([0, 0, 0, 0]);
      cryptoObj.getRandomValues(bytes);
      return Array.from(bytes, function (b) {
        return b.toString(16).padStart(2, "0");
      }).join("");
    }
    return Math.random().toString(16).slice(2, 10).padEnd(8, "0").slice(0, 8);
  }

  function _createLogger() {
    const ring = [];
    const debugMode = new URLSearchParams(location.search).has("debug");
    const sessionId = _makeSessionId();

    function _push(level, scope, payload) {
      const fullScope = scope.indexOf("ewash.") === 0 ? scope : "ewash." + scope;
      const entry = Object.assign(
        {
          t: new Date().toISOString(),
          level: level,
          scope: fullScope,
          session: sessionId,
        },
        payload || {}
      );
      ring.push(entry);
      if (ring.length > LOG_RING_LIMIT) ring.shift();

      const suffix = level === "error" ? ".fatal" : level === "warn" ? ".warn" : "";
      const label = "[" + fullScope + suffix + "]";
      if (level === "error") console.error(label, entry);
      else if (level === "warn") console.warn(label, entry);
      else console.info(label, entry);

      try {
        window.dispatchEvent(new CustomEvent("ewashlog", { detail: entry }));
      } catch (_) {
        // Logging must never break the customer flow.
      }
    }

    async function hash(value) {
      if (!value) return "";
      try {
        const digest = await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(String(value))
        );
        return Array.from(new Uint8Array(digest))
          .slice(0, 4)
          .map(function (b) {
            return b.toString(16).padStart(2, "0");
          })
          .join("");
      } catch (_) {
        return "";
      }
    }

    return {
      info: function (scope, payload) { _push("info", scope, payload); },
      warn: function (scope, payload) { _push("warn", scope, payload); },
      fatal: function (scope, payload) { _push("error", scope, payload); },
      snapshot: function () { return ring.slice(); },
      hash: hash,
      sessionId: sessionId,
      debugMode: debugMode,
    };
  }

  const EwashLog = window.EwashLog || _createLogger();
  window.EwashLog = EwashLog;
  if (EwashLog.debugMode) {
    EwashLog.info("lifecycle.boot", {
      url: location.href,
      ua: navigator.userAgent,
      api_base: window.EWASH_API_BASE || "",
    });
  }

  function _base() {
    return window.EWASH_API_BASE || "";
  }

  function _durationMs(startedAt) {
    return (performance.now() - startedAt).toFixed(0);
  }

  function _jsonErrorBody(resp) {
    return resp.json().catch(function () {
      return {
        error_code: "non_json",
        message: resp.statusText,
      };
    });
  }

  function _setDuration(err, duration) {
    if (err && typeof err === "object") {
      try {
        err.duration_ms = +duration;
      } catch (_) {
        // Some browser error objects are not extensible.
      }
    }
  }

  function _setRetryAfter(err, resp, errBody) {
    if (!err || typeof err !== "object") return;
    const header = resp && resp.headers ? resp.headers.get("Retry-After") : null;
    const raw = header || (errBody && (errBody.retry_after || errBody.retry_after_seconds));
    const parsed = Number(raw);
    if (Number.isFinite(parsed) && parsed > 0) err.retry_after = parsed;
  }

  function _apiScope(path) {
    const cleanPath = path.split("?")[0].replace(/^\/api\/v1\/?/, "");
    const scope = cleanPath || "root";
    return "api." + scope.replace(/^\//, "").replace(/\//g, "_").replace(/-/g, "_");
  }

  async function _fetch(path, options) {
    options = options || {};

    const method = options.method || "GET";
    const headers = options.headers || {};
    const body = Object.prototype.hasOwnProperty.call(options, "body") ? options.body : null;
    const timeout = Object.prototype.hasOwnProperty.call(options, "timeout")
      ? options.timeout
      : DEFAULT_TIMEOUT_MS;

    const controller = new AbortController();
    const timeoutId = setTimeout(function () {
      controller.abort();
    }, timeout);
    const startedAt = performance.now();
    const retryCount = options.retry_count || 0;
    const scope = _apiScope(path);

    EwashLog.info(scope, {
      path: path,
      method: method,
      retry_count: retryCount,
    });

    try {
      const resp = await fetch(_base() + path, {
        method: method,
        headers: Object.assign(
          {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          headers
        ),
        body: body !== null ? JSON.stringify(body) : null,
        signal: controller.signal,
        mode: "cors",
      });
      const duration = _durationMs(startedAt);

      if (!resp.ok) {
        const errBody = await _jsonErrorBody(resp);
        const err = new Error(errBody.message || errBody.detail || resp.statusText);
        err.error_code = errBody.error_code || "http_" + resp.status;
        err.status = resp.status;
        err.field = errBody.field || errBody.loc || null;
        _setRetryAfter(err, resp, errBody);
        _setDuration(err, duration);
        err._ewashLogged = true;
        const payload = {
          path: path,
          method: method,
          status: resp.status,
          duration_ms: +duration,
          error_code: err.error_code,
          retry_count: retryCount,
        };
        if (resp.status >= 500) EwashLog.fatal(scope, payload);
        else EwashLog.warn(scope, payload);
        throw err;
      }

      EwashLog.info(scope, {
        path: path,
        method: method,
        status: resp.status,
        duration_ms: +duration,
        retry_count: retryCount,
      });
      if (resp.status === 204 || resp.status === 304) {
        return null;
      }
      return await resp.json();
    } catch (err) {
      if (err && !err.error_code) {
        err.error_code = err.name === "AbortError" ? "timeout" : "network_error";
      }
      if (!err || !err._ewashLogged) {
        const failedDuration = _durationMs(startedAt);
        _setDuration(err, failedDuration);
        EwashLog.fatal(scope, {
          path: path,
          method: method,
          status: 0,
          duration_ms: +failedDuration,
          error_code: (err && err.error_code) || "network_error",
          retry_count: retryCount,
        });
      }
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async function _fetchWithRetry(path, options, retryConfig) {
    const cfg = retryConfig || {};
    const retries = cfg.retries === undefined ? 2 : cfg.retries;
    const backoffMs = cfg.backoffMs === undefined ? 500 : cfg.backoffMs;

    let lastErr;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        return await _fetch(path, Object.assign({}, options || {}, { retry_count: attempt }));
      } catch (err) {
        lastErr = err;
        // 4xx is deterministic — retrying changes nothing, so surface immediately.
        if (err && typeof err.status === "number" && err.status >= 400 && err.status < 500) {
          throw err;
        }
        // 5xx / network errors / aborts → backoff and retry while attempts remain.
        if (attempt < retries) {
          const delay = backoffMs * Math.pow(2, attempt);
          EwashLog.info("api.retry", {
            path: path,
            method: (options && options.method) || "GET",
            delay_ms: delay,
            retry_count: attempt + 1,
            error_code: (err && err.error_code) || (err && err.name) || "error",
          });
          await new Promise(function (resolve) {
            setTimeout(resolve, delay);
          });
        }
      }
    }
    throw lastErr;
  }

  function _getToken() {
    try {
      return localStorage.getItem(BOOKINGS_STORAGE_KEY) || "";
    } catch (_) {
      // Private mode, storage disabled — treat as "no token", caller decides.
      EwashLog.warn("localstorage.error", { op: "get", key: "bookings_token" });
      return "";
    }
  }

  function _saveToken(token) {
    if (!token) return;
    try {
      localStorage.setItem(BOOKINGS_STORAGE_KEY, token);
    } catch (_) {
      // Storage quota / private mode — best-effort persistence only.
      EwashLog.warn("localstorage.error", { op: "set", key: "bookings_token" });
    }
  }

  function _savePhone(phone) {
    if (!phone) return;
    try {
      localStorage.setItem(PHONE_STORAGE_KEY, phone);
    } catch (_) {
      // ditto.
      EwashLog.warn("localstorage.error", { op: "set", key: "phone" });
    }
  }

  async function getBootstrap(options) {
    const params = options || {};
    const qs = new URLSearchParams();
    if (params.category) qs.set("category", params.category);
    if (params.promo) qs.set("promo", params.promo);
    const query = qs.toString();
    const path = "/api/v1/bootstrap" + (query ? "?" + query : "");
    return await _fetchWithRetry(path);
  }

  async function validatePromo(params) {
    return await _fetch("/api/v1/promos/validate", {
      method: "POST",
      body: { code: params.code, category: params.category },
    });
  }

  async function submitBooking(payload) {
    // Auto-inject any existing bookings_token from localStorage so the server
    // can echo it back on a returning customer (and so a retry of the same
    // client_request_id remains idempotent on the same device).
    const existingToken = _getToken();
    const requestBody = Object.assign(
      {},
      payload,
      existingToken ? { bookings_token: existingToken } : {}
    );
    const phoneHash = await EwashLog.hash(payload && payload.phone);
    EwashLog.info("booking.confirm", {
      phone_hash: phoneHash,
      category: payload && payload.category,
      service: payload && payload.service_id,
      total_dh: payload && payload.total_dh,
      has_promo: !!(payload && payload.promo_code),
      addon_count: payload && payload.addon_ids ? payload.addon_ids.length : 0,
      client_request_id: payload && payload.client_request_id,
    });
    const response = await _fetch("/api/v1/bookings", {
      method: "POST",
      body: requestBody,
    });

    // Server always returns the canonical bookings_token (echoed when reused,
    // freshly minted on first contact). Persist it once so subsequent reads
    // on `getMyBookings` can authenticate.
    if (response && response.bookings_token) _saveToken(response.bookings_token);
    if (payload && payload.phone) _savePhone(payload.phone);

    if (response) {
      EwashLog.info("booking.confirmed", {
        ref: response.ref,
        total_dh: response.total_dh,
        token_changed: existingToken !== response.bookings_token,
        duration_ms: response.duration_ms,
        is_idempotent_replay: response.is_idempotent_replay === true,
      });
    }
    return response;
  }

  async function getMyBookings() {
    const token = _getToken();
    if (!token) {
      // Surface as a structured error so the Bookings tab can render an
      // "open a booking first to enable history" empty state instead of a
      // generic network failure.
      const err = new Error("No bookings_token in localStorage");
      err.error_code = "no_local_token";
      throw err;
    }
    return await _fetchWithRetry("/api/v1/bookings", {
      headers: { "X-Ewash-Token": token },
    });
  }

  async function revokeToken(params) {
    const token = _getToken();
    if (!token) {
      const err = new Error("No bookings_token in localStorage");
      err.error_code = "no_local_token";
      throw err;
    }
    const scope = params && params.scope ? params.scope : "current";
    const response = await _fetch("/api/v1/tokens/revoke", {
      method: "POST",
      headers: { "X-Ewash-Token": token },
      body: { scope: scope },
    });
    if (response && response.new_token) _saveToken(response.new_token);
    return response;
  }

  window.EwashAPI = {
    _fetch: _fetch,
    _TOKEN_KEY: BOOKINGS_STORAGE_KEY,
    _PHONE_KEY: PHONE_STORAGE_KEY,
    _getToken: _getToken,
    getBootstrap: getBootstrap,
    validatePromo: validatePromo,
    submitBooking: submitBooking,
    getMyBookings: getMyBookings,
    revokeToken: revokeToken,
  };
})();
