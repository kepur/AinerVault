export async function request<T>(path: string, body?: unknown, method = body === undefined ? "GET" : "POST"): Promise<T> {
  let r:Response|undefined;
  // Service reloads may briefly close a connection. Retry reads only; never
  // automatically repeat a generation or a delegated translation submission.
  for(let attempt=0;attempt<4;attempt++){
    try{
      r=await fetch(path,{method,headers:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body)});
      if(method==='GET'&&[502,503,504].includes(r.status)&&attempt<3){await new Promise(done=>setTimeout(done,500*2**attempt));continue;}
      break;
    }catch(e){
      if(method!=='GET'||attempt===3||!(e instanceof TypeError))throw e;
      await new Promise(done=>setTimeout(done,500*2**attempt));
    }
  }
  if(!r)throw new Error('暂时无法读取服务，请稍后刷新');
  const raw = await r.text();
  let d: unknown;
  try { d = JSON.parse(raw); } catch { d = raw; }
  if (!r.ok) {
    const v = d && typeof d === "object" && "detail" in d ? d.detail : d;
    throw new Error(typeof v === "string" ? v : JSON.stringify(v));
  }
  return d as T;
}

// Separate local executor, shared core media. No core restart for this integration.
// Explicit URL override supports hosts with a different executor port.
export const engine = import.meta.env.VITE_COMIC_URL || `http://${location.hostname === "localhost" ? "localhost" : "127.0.0.1"}:8190`;
export const comicRequest = <T,>(path: string, body?: unknown) => request<T>(engine + path, body);

export interface EngineTask {
  task_id: string; capability: string; status: string; progress: number; attempt: number;
  submitted_at: string; output: Record<string, unknown> | null;
  input?: Record<string, unknown> | null;
  error: { code: string; message: string; retryable?: boolean } | null;
  context: { production_id?: string; chapter_id?: string; plan_id?: string; locale?: string; shot_id?: string; frame_asset_id?:string; source_id?:string;kind?:string };
  usage: { duration_ms: number | null };
}
export interface Discovery { capabilities: { capability: string }[]; pending: { capability: string; label: string; reason: string }[] }

export async function submit(capability: string, input: unknown): Promise<EngineTask> {
  const bytes = new TextEncoder().encode(JSON.stringify({ capability, input }));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  const key = "sha256:" + Array.from(new Uint8Array(hash)).map(v => v.toString(16).padStart(2, "0")).join("");
  return comicRequest<EngineTask>("/cap/v1/tasks", { capability, input, idempotency_key: key, options: { timeout_ms: 1200000 } });
}

export function media(url?: string | null): string | null {
  if (!url) return null;
  const u = new URL(url, location.origin);
  return u.pathname.startsWith("/media/") && [location.hostname, "localhost", "127.0.0.1"].includes(u.hostname) ? u.pathname : null;
}

export function download(name: string, content: string, mime = "text/plain;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
