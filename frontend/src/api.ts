// Typed client for the AgentFYP backend (async job pipeline + lookups).
//
// Flow: POST /process -> { video_id } (a job id); poll GET /jobs/{id} until the
// job is completed/failed (surfacing stage + progress); then GET /video/{id} for
// the stored record. Slides, Mermaid, chat and history search have their own
// endpoints.

export const API_URL: string =
  import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface ProcessRequest {
  youtube_url: string;
  generate_slides?: boolean;
  video_type?: string | null;
  language?: string | null;
}

export interface JobCreated {
  video_id: string;
  status: string;
}

export interface PipelineResult {
  video_id: string;
  youtube_id?: string | null;
  video_type?: string | null;
  summary_md?: string | null;
  slides_path?: string | null;
  cached?: boolean;
}

export type JobState = 'pending' | 'running' | 'completed' | 'failed';

export interface JobStatus {
  video_id: string;
  status: JobState;
  stage: string;
  progress: number;
  detail?: string | null;
  cached: boolean;
  result?: PipelineResult | null;
  error?: string | null;
}

export interface VideoRecord {
  video_id: string;
  youtube_id: string;
  url: string;
  title: string;
  video_type?: string | null;
  summary_md: string;
  slides_path?: string | null;
  mermaid?: string | null;
}

export interface HistoryItem {
  video_id: string;
  youtube_id: string;
  url: string;
  title: string;
  video_type?: string | null;
  summary_md: string;
  has_slides: boolean;
  has_mermaid: boolean;
}

export interface ChatTurn {
  role: 'user' | 'model' | 'assistant';
  content: string;
}

export interface Citation {
  timestamp: string;
  start: number;
  quote: string;
}

export interface ChatReply {
  answer: string;
  citations: Citation[];
}

export interface SegmentHit {
  start: number;
  timestamp: string;
  text: string;
}

export interface HistoryHit {
  video_id: string;
  youtube_id: string;
  title: string;
  url: string;
  video_type: string;
  score: number;
  segments: SegmentHit[];
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function startProcess(req: ProcessRequest): Promise<JobCreated> {
  const res = await fetch(`${API_URL}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  return asJson<JobCreated>(res);
}

export async function getJob(videoId: string): Promise<JobStatus> {
  return asJson<JobStatus>(await fetch(`${API_URL}/jobs/${videoId}`));
}

export async function getVideo(videoId: string): Promise<VideoRecord> {
  return asJson<VideoRecord>(await fetch(`${API_URL}/video/${videoId}`));
}

export async function getHistory(): Promise<HistoryItem[]> {
  const data = await asJson<{ items: HistoryItem[] }>(
    await fetch(`${API_URL}/history`),
  );
  return data.items;
}

export async function searchHistory(
  q: string,
  topK = 5,
): Promise<HistoryHit[]> {
  const url = `${API_URL}/history/search?q=${encodeURIComponent(q)}&top_k=${topK}`;
  const data = await asJson<{ query: string; results: HistoryHit[] }>(
    await fetch(url),
  );
  return data.results;
}

export async function getMermaid(videoId: string): Promise<string> {
  const data = await asJson<{ video_id: string; mermaid: string }>(
    await fetch(`${API_URL}/mermaid/${videoId}`),
  );
  return data.mermaid;
}

export async function getTranscript(videoId: string): Promise<SegmentHit[]> {
  const data = await asJson<{ video_id: string; segments: SegmentHit[] }>(
    await fetch(`${API_URL}/transcript/${videoId}`),
  );
  return data.segments;
}

export async function chat(
  videoId: string,
  message: string,
  history: ChatTurn[],
): Promise<ChatReply> {
  const res = await fetch(`${API_URL}/chat/${videoId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  });
  const data = await asJson<{
    video_id: string;
    answer: string;
    citations: Citation[];
  }>(res);
  return { answer: data.answer, citations: data.citations || [] };
}

export function pptUrl(videoId: string): string {
  return `${API_URL}/ppt/${videoId}`;
}

/** True when a job error / detail indicates an unresolvable YouTube URL. */
export function isUnresolvableUrl(job: JobStatus): boolean {
  const text = `${job.error ?? ''} ${job.detail ?? ''}`.toLowerCase();
  return (
    text.includes('could not parse') ||
    text.includes('video id') ||
    text.includes('解析')
  );
}

/**
 * Poll a job until it reaches a terminal state, invoking ``onTick`` on every
 * status update so the UI can show live stage/progress. Resolves with the final
 * JobStatus (completed or failed).
 */
export async function pollJob(
  videoId: string,
  onTick: (job: JobStatus) => void,
  opts: { intervalMs?: number; signal?: AbortSignal } = {},
): Promise<JobStatus> {
  const intervalMs = opts.intervalMs ?? 1500;
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const job = await getJob(videoId);
    onTick(job);
    if (job.status === 'completed' || job.status === 'failed') return job;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
