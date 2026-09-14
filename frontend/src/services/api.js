// Thin fetch wrapper. Relative /api URLs work through the Vite proxy in
// development and through Nginx / FastAPI static hosting in production.
const BASE = import.meta.env.VITE_API_BASE || '';

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${response.status} ${detail}`);
  }
  return response.status === 204 ? null : response.json();
}

export const apiGet = (path, options) => request(path, options);
export const apiPost = (path, body, options) => request(path, { method: 'POST', body: JSON.stringify(body), ...options });
export const apiPatch = (path, body, options) => request(path, { method: 'PATCH', body: JSON.stringify(body), ...options });
