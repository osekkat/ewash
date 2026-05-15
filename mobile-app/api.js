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

  window.EwashAPI = {
    _fetch: _fetch,
    _TOKEN_KEY: BOOKINGS_STORAGE_KEY,
    _PHONE_KEY: PHONE_STORAGE_KEY,
  };
})();
