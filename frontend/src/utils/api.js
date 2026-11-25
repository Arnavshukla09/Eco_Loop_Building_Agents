// Credentials last only for this browser tab. Remove keys saved by older builds.
export function getApiToken() {
  try {
    localStorage.removeItem('eco_api_key');
    return sessionStorage.getItem('eco_api_key') || '';
  } catch {
    return '';
  }
}

export function setApiToken(token) {
  try {
    localStorage.removeItem('eco_api_key');
    if (token) sessionStorage.setItem('eco_api_key', token);
    else sessionStorage.removeItem('eco_api_key');
  } catch {
    // The current form still works when the browser blocks storage.
  }
}

export function apiError(data, fallback) {
  const detail = data?.detail ?? data?.message;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(item => typeof item?.msg === 'string' ? item.msg : '')
      .filter(Boolean).join('; ') || fallback;
  }
  return fallback;
}
