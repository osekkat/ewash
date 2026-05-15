(function () {
  const BOOKINGS_STORAGE_KEY = ["ewash.bookings", "token"].join("_");
  const PHONE_STORAGE_KEY = "ewash.phone";
  const DEFAULT_TIMEOUT_MS = 10000;

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
        _setDuration(err, duration);
        err._ewashLogged = true;
        console.warn("[ewash.api]", method, path, "->", resp.status, err.error_code, duration + "ms");
        throw err;
      }

      console.info("[ewash.api]", method, path, "->", resp.status, duration + "ms");
      if (resp.status === 204 || resp.status === 304) {
        return null;
      }
      return await resp.json();
    } catch (err) {
      if (!err || !err._ewashLogged) {
        const failedDuration = _durationMs(startedAt);
        _setDuration(err, failedDuration);
        console.warn(
          "[ewash.api]",
          method,
          path,
          "->",
          (err && (err.name || err.message)) || "error",
          failedDuration + "ms"
        );
      }
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  function _getToken() {
    try {
      return localStorage.getItem(BOOKINGS_STORAGE_KEY) || "";
    } catch (_) {
      // Private mode, storage disabled — treat as "no token", caller decides.
      return "";
    }
  }

  function _saveToken(token) {
    if (!token) return;
    try {
      localStorage.setItem(BOOKINGS_STORAGE_KEY, token);
    } catch (_) {
      // Storage quota / private mode — best-effort persistence only.
    }
  }

  function _savePhone(phone) {
    if (!phone) return;
    try {
      localStorage.setItem(PHONE_STORAGE_KEY, phone);
    } catch (_) {
      // ditto.
    }
  }

  async function getBootstrap(options) {
    const params = options || {};
    const qs = new URLSearchParams();
    if (params.category) qs.set("category", params.category);
    if (params.promo) qs.set("promo", params.promo);
    const query = qs.toString();
    const path = "/api/v1/bootstrap" + (query ? "?" + query : "");
    return await _fetch(path);
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
      console.info("[ewash.api.booking]", {
        ref: response.ref,
        total: response.total_dh,
        token_changed: existingToken !== response.bookings_token,
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
    return await _fetch("/api/v1/bookings", {
      headers: { "X-Ewash-Token": token },
    });
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
  };
})();
