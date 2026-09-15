// Thin fetch wrapper. Relative /api URLs work through the Vite proxy in
// development and through Nginx / FastAPI static hosting in production.
// An optional API token (backend VELES_API_TOKEN) is kept in localStorage and
// sent as X-API-Key.
const BASE = import.meta.env.VITE_API_BASE || '';
const TOKEN_KEY = 'veles_api_token';

export function getApiToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export function setApiToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

export function authHeaders() {
  const token = getApiToken();
  return token ? { 'X-API-Key': token } : {};
}

export function apiUrl(path) {
  return `${BASE}${path}`;
}

async function request(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...authHeaders(), ...(options.headers || {}) },
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

/** Download a file produced by the API (PDF/CSV/JSON) with the token attached. */
export async function downloadFile(path, filename, options = {}) {
  const response = await fetch(apiUrl(path), { ...options, headers: { ...authHeaders(), ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const blob = await response.blob();
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}
