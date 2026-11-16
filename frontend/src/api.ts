const API_BASE = (import.meta as unknown as { env: Record<string, string> }).env.VITE_API_URL?.replace(/\/$/, '') ?? '';
export const tokenStore = {
  get: () => sessionStorage.getItem('hireline_token'),
  set: (token: string) => sessionStorage.setItem('hireline_token', token),
  clear: () => sessionStorage.removeItem('hireline_token'),
};

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = tokenStore.get();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let response: Response;
  try { response = await fetch(`${API_BASE}/api${path}`, { ...options, headers }); }
  catch { throw new Error('The workspace is temporarily unreachable. A free backend may need a minute to wake. Please retry.'); }
  if (response.status === 401 && token) {
    tokenStore.clear(); window.dispatchEvent(new Event('hireline:unauthorized'));
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = result.detail ?? result.message;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d: {msg?: string}) => d.msg).join('; ') : 'The request could not be completed.';
    throw new Error(message);
  }
  return result as T;
}

export const post = <T,>(path: string, body: unknown = {}) => api<T>(path, { method: 'POST', body: JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(body) });

export async function downloadDocument(id: string, filename: string) {
  const token = tokenStore.get();
  if (!token) throw new Error('Sign in to view original documents.');
  const response = await fetch(`${API_BASE}/api/documents/${id}/download`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error('This document could not be downloaded. Check your permissions and try again.');
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
