import { Children, cloneElement, isValidElement, useEffect, useRef, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import {
  Button,
  Input,
  Card,
  Modal,
  Checkbox,
  Tabs,
  Loading,
  Time,
  Divider,
} from 'animal-island-ui';
import ReactMarkdown from 'react-markdown';
import { Mermaid } from './Mermaid';
import { YouTubePlayer } from './YouTubePlayer';
import {
  startProcess,
  pollJob,
  getVideo,
  getHistory,
  searchHistory,
  getMermaid,
  getTranscript,
  chat as chatApi,
  pptUrl,
  isUnresolvableUrl,
  getApiKey,
  setApiKey,
  getApiUrl,
  setApiUrl,
  getConfig,
  API_URL,
} from './api';
import type {
  JobStatus,
  VideoRecord,
  HistoryItem,
  HistoryHit,
  ChatTurn,
  Citation,
  SegmentHit,
} from './api';

type Page = 'upload' | 'map' | 'chat';

interface ChatMessage {
  id: string;
  sender: 'secretary' | 'user';
  text: string;
  citations?: Citation[];
}

const STAGE_LABELS: Record<string, string> = {
  pending: '排隊中',
  starting: '準備中',
  ingesting: '擷取影片資訊',
  transcribing: '下載並以 Whisper 轉錄',
  summarizing: '產生結構化摘要',
  generating_slides: '製作投影片',
  indexing: '寫入記憶',
  cached: '已從記憶快取載入',
  completed: '完成',
  failed: '失敗',
};

function welcomeText(title: string, summary: string): string {
  return `我已經幫你讀完《${title}》的內容囉！以下是這部影片的結構化重點摘要，有任何細節問題都可以問我：\n\n${summary}`;
}

// ── Timestamp helpers: turn [MM:SS] / [H:MM:SS] text into seek buttons ───────
// NOTE: this pattern and `tsToSeconds` mirror the backend
// (`src/agent_fyp/tools/chat.py`: `_TIMESTAMP_RE` / `_marker_to_seconds`).
// Keep the two in sync.
const TS_RE = /\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]/g;

function tsToSeconds(a: string, b: string, c?: string): number {
  return c == null
    ? Number(a) * 60 + Number(b)
    : Number(a) * 3600 + Number(b) * 60 + Number(c);
}

function linkifyTimestamps(text: string, onSeek: (s: number) => void): ReactNode[] {
  const out: ReactNode[] = [];
  const re = new RegExp(TS_RE.source, 'g');
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const secs = tsToSeconds(m[1], m[2], m[3]);
    out.push(
      <button
        key={`t${i++}`}
        type="button"
        className="ts-link"
        onClick={() => onSeek(secs)}
      >
        {m[0]}
      </button>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// Recursively walk every descendant text node so timestamps nested inside
// formatting (e.g. <strong>[01:05]</strong>) get linkified too, not just the
// top-level string children of an <li>/<p>.
function renderWithSeek(children: ReactNode, onSeek: (s: number) => void): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child === 'string') return linkifyTimestamps(child, onSeek);
    if (isValidElement(child)) {
      const el = child as ReactElement<{ children?: ReactNode }>;
      if (el.props.children == null) return child;
      return cloneElement(el, undefined, renderWithSeek(el.props.children, onSeek));
    }
    return child;
  });
}

// ── Mermaid knowledge-map panel (lazy: fetches on first view) ────────────────
function MermaidPanel({ videoId }: { videoId: string }) {
  const [code, setCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setCode(null);
    getMermaid(videoId)
      .then((m) => {
        if (!cancelled) setCode(m);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  if (loading)
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 24 }}>
        <Loading active /> <span>正在生成知識圖譜...</span>
      </div>
    );
  if (error)
    return <div style={{ color: '#e05a5a', padding: 16 }}>知識圖譜生成失敗：{error}</div>;
  if (!code) return null;
  return <Mermaid code={code} />;
}

// ── Transcript viewer panel (lazy, filterable, click-to-seek) ────────────────
function TranscriptPanel({
  videoId,
  onSeek,
}: {
  videoId: string;
  onSeek: (s: number) => void;
}) {
  const [segments, setSegments] = useState<SegmentHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSegments(null);
    getTranscript(videoId)
      .then((s) => {
        if (!cancelled) setSegments(s);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  if (loading)
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 24 }}>
        <Loading active /> <span>載入逐字稿...</span>
      </div>
    );
  if (error)
    return <div style={{ color: '#e05a5a', padding: 16 }}>逐字稿載入失敗：{error}</div>;
  if (!segments) return null;

  const q = filter.trim().toLowerCase();
  const shown = q ? segments.filter((s) => s.text.toLowerCase().includes(q)) : segments;

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Input
          size="small"
          placeholder="在逐字稿中搜尋關鍵字..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          allowClear
          onClear={() => setFilter('')}
        />
      </div>
      <div
        style={{
          maxHeight: 440,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
        }}
      >
        {shown.length === 0 ? (
          <div style={{ color: '#c4b89e', fontStyle: 'italic', padding: 12 }}>
            找不到符合的內容
          </div>
        ) : (
          shown.map((s, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onSeek(s.start)}
              style={{
                display: 'flex',
                gap: 12,
                textAlign: 'left',
                background: 'transparent',
                border: 'none',
                borderBottom: '1px dashed #eee',
                padding: '8px 6px',
                cursor: 'pointer',
                fontFamily: 'inherit',
                color: '#725d42',
              }}
            >
              <span
                style={{ color: '#11a89b', fontWeight: 700, minWidth: 64, flexShrink: 0 }}
              >
                {s.timestamp}
              </span>
              <span style={{ fontSize: 14, lineHeight: 1.5 }}>{s.text}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

function hitToItem(hit: HistoryHit): HistoryItem {
  return {
    video_id: hit.video_id,
    youtube_id: hit.youtube_id,
    url: hit.url,
    title: hit.title,
    video_type: hit.video_type,
    summary_md: '',
    has_slides: false,
    has_mermaid: false,
  };
}

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>('upload');
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [generateSlides, setGenerateSlides] = useState(true);
  const [chatInput, setChatInput] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);

  // ── Settings (BYOK Gemini key + backend API URL, both runtime-configurable) ──
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [apiUrlInput, setApiUrlInput] = useState('');
  const [hasKey, setHasKey] = useState<boolean>(() => Boolean(getApiKey()));
  const [requiresKey, setRequiresKey] = useState(false);

  const [isProcessing, setIsProcessing] = useState(false);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [current, setCurrent] = useState<VideoRecord | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatSending, setChatSending] = useState(false);

  const [historyList, setHistoryList] = useState<HistoryItem[]>([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<HistoryHit[] | null>(null);
  const [searching, setSearching] = useState(false);

  const chatBottomRef = useRef<HTMLDivElement>(null);

  // Shared YouTube player + seek state (player lives on the map page).
  const playerRef = useRef<any>(null);
  const [playerReady, setPlayerReady] = useState(false);
  const pendingSeekRef = useRef<number | null>(null);

  const handlePlayerReady = (player: any) => {
    playerRef.current = player;
    setPlayerReady(true);
    if (pendingSeekRef.current != null) {
      try {
        player.seekTo(pendingSeekRef.current, true);
        player.playVideo?.();
      } catch {
        /* ignore */
      }
      pendingSeekRef.current = null;
    }
  };

  const seekTo = (seconds: number) => {
    const p = playerRef.current;
    if (p && playerReady) {
      try {
        p.seekTo(seconds, true);
        p.playVideo?.();
      } catch {
        /* ignore */
      }
      if (currentPage !== 'map') setCurrentPage('map');
    } else {
      pendingSeekRef.current = seconds;
      setCurrentPage('map');
    }
  };

  const openSettings = () => {
    setApiKeyInput(getApiKey());
    setApiUrlInput(getApiUrl());
    setSettingsOpen(true);
  };

  const saveSettings = () => {
    setApiUrl(apiUrlInput);
    setApiKey(apiKeyInput);
    setHasKey(Boolean(apiKeyInput.trim()));
    setSettingsOpen(false);
  };

  // On load, ask the backend whether it requires the user to bring their own
  // Gemini key; if so and none is stored yet, open settings to prompt for one.
  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((cfg) => {
        if (cancelled) return;
        setRequiresKey(cfg.requires_api_key);
        if (cfg.requires_api_key && !getApiKey()) openSettings();
      })
      .catch(() => {
        /* backend unreachable; the URL can be fixed via settings */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The player only lives on the map page and remounts per youtube_id, so its
  // readiness is invalid after a video change or when we leave the map page.
  useEffect(() => {
    setPlayerReady(false);
    playerRef.current = null;
  }, [current?.youtube_id]);

  useEffect(() => {
    if (currentPage !== 'map') {
      setPlayerReady(false);
      playerRef.current = null;
    }
  }, [currentPage]);

  const refreshHistory = async () => {
    try {
      setHistoryList(await getHistory());
    } catch (e) {
      console.error('無法獲取歷史紀錄:', e);
    }
  };

  useEffect(() => {
    refreshHistory();
  }, []);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  const openVideo = (record: VideoRecord, cached: boolean) => {
    setCurrent(record);
    setFromCache(cached);
    setChatMessages([
      {
        id: 'welcome',
        sender: 'secretary',
        text: welcomeText(record.title || '這部影片', record.summary_md),
      },
    ]);
    setCurrentPage('map');
  };

  const handleSelectHistory = async (item: HistoryItem) => {
    try {
      const record = await getVideo(item.video_id);
      openVideo(record, false);
    } catch (e) {
      setErrorMsg(`無法載入此紀錄：${(e as Error).message}`);
    }
  };

  // Load a searched video (if not current) then seek to the matched moment.
  const openAndSeek = async (hit: HistoryHit, seconds: number) => {
    if (current?.video_id === hit.video_id && playerReady) {
      seekTo(seconds);
      return;
    }
    pendingSeekRef.current = seconds;
    await handleSelectHistory(hitToItem(hit));
  };

  const handleExtract = async () => {
    const url = youtubeUrl.trim();
    if (!url) {
      setErrorMsg('請先輸入 YouTube 網址唷！🍃');
      return;
    }
    setErrorMsg(null);
    setIsProcessing(true);
    setJob(null);
    try {
      const created = await startProcess({
        youtube_url: url,
        generate_slides: generateSlides,
      });
      const final = await pollJob(created.video_id, setJob);

      if (final.status === 'failed') {
        setErrorMsg(
          isUnresolvableUrl(final)
            ? 'Unable to resolve this URL（無法解析此網址，已停止處理）'
            : `處理失敗：${final.error || final.detail || '請檢查影片是否為私人或已移除'}`,
        );
        return;
      }

      const recordId = final.result?.video_id || created.video_id;
      const record = await getVideo(recordId);
      const cached = Boolean(final.cached || final.result?.cached);
      setYoutubeUrl('');
      openVideo(record, cached);
      refreshHistory();
    } catch (e) {
      setErrorMsg(`發生錯誤：${(e as Error).message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSendMessage = async () => {
    const text = chatInput.trim();
    if (!text || !current || chatSending) return;

    const userMessage: ChatMessage = {
      id: `u-${chatMessages.length}`,
      sender: 'user',
      text,
    };
    setChatMessages((prev) => [...prev, userMessage]);
    setChatInput('');
    setChatSending(true);

    // Build grounded history from prior exchanges (skip the welcome blurb).
    const history: ChatTurn[] = chatMessages
      .filter((m) => m.id !== 'welcome')
      .map((m) => ({
        role: m.sender === 'user' ? 'user' : 'model',
        content: m.text,
      }));

    try {
      const reply = await chatApi(current.video_id, text, history);
      setChatMessages((prev) => [
        ...prev,
        {
          id: `s-${prev.length}`,
          sender: 'secretary',
          text: reply.answer,
          citations: reply.citations,
        },
      ]);
    } catch (e) {
      setChatMessages((prev) => [
        ...prev,
        {
          id: `s-${prev.length}`,
          sender: 'secretary',
          text: `抱歉，回覆時發生錯誤：${(e as Error).message}`,
        },
      ]);
    } finally {
      setChatSending(false);
    }
  };

  const handleSearch = async () => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    try {
      setSearchResults(await searchHistory(q, 5));
    } catch (e) {
      console.error('搜尋失敗:', e);
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const stageLabel = job ? STAGE_LABELS[job.stage] ?? job.stage : '';
  const pct = job ? Math.round((job.progress || 0) * 100) : 0;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
        backgroundColor: '#f8f8f0',
        boxSizing: 'border-box',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '5px 32px',
          backgroundColor: '#fff',
          borderBottom: '4px solid #9f927d',
          boxShadow: '0 4px 10px rgba(107, 92, 67, 0.08)',
          zIndex: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <button
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            style={{
              background: '#fdfdf5',
              border: '2px solid #9f927d',
              borderRadius: '8px',
              padding: '6px 10px',
              cursor: 'pointer',
              fontSize: '16px',
              color: '#794f27',
              boxShadow: '0 2px 0 0 #bdaea0',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            {isSidebarOpen ? '◀ 收回紀錄' : '▶ 歷史紀錄'}
          </button>
          <h1
            style={{
              margin: 0,
              fontSize: '24px',
              fontWeight: 800,
              color: '#794f27',
              letterSpacing: '1px',
            }}
          >
            YouTube 影片知識萃取助理 — 知識無人島
          </h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={openSettings}
            title="設定 API 金鑰與後端網址"
            style={{
              background: hasKey ? '#fdfdf5' : '#fff4d6',
              border: `2px solid ${hasKey ? '#9f927d' : '#e0a92e'}`,
              borderRadius: '8px',
              padding: '6px 12px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 700,
              color: '#794f27',
              boxShadow: '0 2px 0 0 #bdaea0',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            ⚙️ 設定
            <span
              title={hasKey ? '已設定 API 金鑰' : '尚未設定 API 金鑰'}
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: hasKey ? '#3fb27f' : '#e0a92e',
                display: 'inline-block',
              }}
            />
          </button>
          <div style={{ transform: 'scale(0.95)', transformOrigin: 'right center' }}>
            <Time />
          </div>
        </div>
      </header>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', boxSizing: 'border-box' }}>
        {/* Sidebar: history + semantic search */}
        <aside
          style={{
            width: isSidebarOpen ? '280px' : '0px',
            minWidth: isSidebarOpen ? '280px' : '0px',
            opacity: isSidebarOpen ? 1 : 0,
            backgroundColor: '#fdfdf5',
            borderRight: isSidebarOpen ? '4px solid #9f927d' : '0px solid transparent',
            display: 'flex',
            flexDirection: 'column',
            padding: isSidebarOpen ? '16px 14px' : '16px 0px',
            boxSizing: 'border-box',
            transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s, padding 0.3s',
            overflow: 'hidden',
          }}
        >
          {/* Semantic search (query_history) */}
          <div style={{ fontSize: '14px', fontWeight: 800, color: '#794f27', marginBottom: '8px' }}>
            🔍 語意搜尋
          </div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            <div style={{ flex: 1 }}>
              <Input
                size="small"
                placeholder="搜尋看過的影片..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              />
            </div>
            <Button size="small" onClick={handleSearch} disabled={searching}>
              {searching ? '...' : '搜尋'}
            </Button>
          </div>

          {searchResults !== null && (
            <div
              style={{
                marginBottom: 10,
                maxHeight: '34%',
                overflowY: 'auto',
                background: '#fff',
                border: '2px solid #e1dacb',
                borderRadius: 12,
                padding: 8,
              }}
            >
              {searchResults.length === 0 ? (
                <div style={{ fontSize: 12, color: '#c4b89e', fontStyle: 'italic' }}>
                  找不到相關影片
                </div>
              ) : (
                searchResults.map((hit) => (
                  <div
                    key={hit.video_id}
                    style={{ borderBottom: '1px dashed #eee', padding: '6px 2px' }}
                  >
                    <div
                      onClick={() => handleSelectHistory(hitToItem(hit))}
                      style={{
                        cursor: 'pointer',
                        fontSize: 12,
                        color: '#725d42',
                        fontWeight: 700,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                      title={hit.title}
                    >
                      📺 {hit.title || hit.youtube_id}{' '}
                      <span style={{ color: '#19c8b9' }}>
                        {(hit.score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div
                      style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}
                    >
                      {hit.segments.slice(0, 4).map((seg, i) => (
                        <button
                          key={i}
                          type="button"
                          className="seg-chip"
                          title={seg.text}
                          onClick={() => openAndSeek(hit, seg.start)}
                        >
                          {seg.timestamp}
                        </button>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          <div style={{ fontSize: '14px', fontWeight: 800, color: '#794f27', marginBottom: '8px' }}>
            📚 歷史清單
          </div>
          <Divider type="line-brown" />
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              marginTop: '10px',
            }}
          >
            {historyList.length === 0 ? (
              <div
                style={{
                  fontSize: '13px',
                  color: '#c4b89e',
                  textAlign: 'center',
                  marginTop: '20px',
                  fontStyle: 'italic',
                }}
              >
                暫無紀錄
              </div>
            ) : (
              historyList.map((item) => (
                <div
                  key={item.video_id}
                  onClick={() => handleSelectHistory(item)}
                  style={{
                    padding: '10px 12px',
                    backgroundColor:
                      current?.video_id === item.video_id ? '#e6f9f6' : '#fff',
                    border:
                      current?.video_id === item.video_id
                        ? '2px solid #19c8b9'
                        : '2px solid #e1dacb',
                    borderRadius: '12px',
                    cursor: 'pointer',
                    fontSize: '13px',
                    color: '#725d42',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    transition: 'all 0.2s',
                  }}
                  title={item.title}
                >
                  📺 {item.title || item.youtube_id}
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Main area */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            padding: '24px',
            gap: '16px',
            overflow: 'hidden',
            boxSizing: 'border-box',
          }}
        >
          <nav style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '4px 0' }}>
            <div style={{ width: '130px' }}>
              <Button size="small" onClick={() => setCurrentPage('upload')} style={{ width: '100%' }}>
                ➕ 提取新影片
              </Button>
            </div>
            <div style={{ width: '130px' }}>
              <Button
                size="small"
                onClick={() => setCurrentPage('map')}
                style={{ width: '100%' }}
                disabled={!current}
              >
                🗺️ 學習地圖
              </Button>
            </div>
            <div style={{ width: '130px' }}>
              <Button
                size="small"
                onClick={() => {
                  setCurrentPage('chat');
                  setIsModalOpen(true);
                }}
                style={{ width: '100%' }}
                disabled={!current}
              >
                💬 島民對話
              </Button>
            </div>
          </nav>

          <main style={{ flex: 1, overflowY: 'auto', boxSizing: 'border-box' }}>
            {/* Upload page */}
            {currentPage === 'upload' && (
              <Card
                color="app-teal"
                style={{
                  minHeight: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  boxSizing: 'border-box',
                }}
              >
                <div style={{ textAlign: 'center', marginBottom: '28px' }}>
                  <h1 style={{ fontSize: '34px', color: '#fff', margin: '0 0 12px 0' }}>
                    歡迎回到無人島！
                  </h1>
                  <p style={{ color: '#fdfdf5', fontSize: '16px', margin: 0 }}>
                    請在下方輸入 YouTube 網址，我們將為您開闢專屬知識地圖
                  </p>
                </div>

                <div
                  style={{
                    maxWidth: '560px',
                    margin: '0 auto',
                    width: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '18px',
                  }}
                >
                  <Input
                    size="large"
                    value={youtubeUrl}
                    onChange={(e) => setYoutubeUrl(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !isProcessing && handleExtract()}
                    placeholder="請輸入 YouTube 影片網址或 11 碼影片 ID"
                    disabled={isProcessing}
                  />

                  <div
                    style={{
                      background: 'rgba(255,255,255,0.85)',
                      borderRadius: 12,
                      padding: '10px 16px',
                    }}
                  >
                    <Checkbox
                      options={[{ label: '同時產生投影片 (.pptx)', value: 'slides' }]}
                      value={generateSlides ? ['slides'] : []}
                      onChange={(vals) => setGenerateSlides(vals.includes('slides'))}
                      disabled={isProcessing}
                    />
                  </div>

                  <Button
                    size="large"
                    onClick={handleExtract}
                    style={{ backgroundColor: '#19c8b9', color: '#fff' }}
                    disabled={isProcessing}
                    loading={isProcessing}
                  >
                    {isProcessing ? '秘書正在全力處理中...' : '提取知識'}
                  </Button>

                  {/* Live progress */}
                  {isProcessing && job && (
                    <div
                      style={{
                        background: '#fff',
                        border: '3px solid #9f927d',
                        borderRadius: 16,
                        padding: '16px 20px',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          marginBottom: 8,
                          color: '#725d42',
                          fontWeight: 700,
                        }}
                      >
                        <span>目前階段：{stageLabel}</span>
                        <span>{pct}%</span>
                      </div>
                      <div
                        style={{
                          height: 14,
                          background: '#f0ece2',
                          borderRadius: 50,
                          overflow: 'hidden',
                          border: '1px solid #e1dacb',
                        }}
                      >
                        <div
                          style={{
                            height: '100%',
                            width: `${pct}%`,
                            background: '#19c8b9',
                            borderRadius: 50,
                            transition: 'width 0.4s ease',
                          }}
                        />
                      </div>
                      {job.detail && (
                        <div style={{ marginTop: 8, fontSize: 13, color: '#8a7b66' }}>
                          {job.detail}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Error */}
                  {errorMsg && (
                    <div
                      style={{
                        background: '#fff0f0',
                        border: '2px solid #e05a5a',
                        borderRadius: 12,
                        padding: '12px 16px',
                        color: '#c0392b',
                        fontWeight: 600,
                      }}
                    >
                      ⚠️ {errorMsg}
                    </div>
                  )}
                </div>
              </Card>
            )}

            {/* Map page: player + summary + transcript + mermaid + slides */}
            {currentPage === 'map' && current && (
              <Card color="app-yellow" style={{ minHeight: '100%', boxSizing: 'border-box' }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    gap: 12,
                    flexWrap: 'wrap',
                  }}
                >
                  <h2 style={{ fontSize: '24px', margin: '0 0 12px 0', color: '#725d42' }}>
                    📌 {current.title || current.youtube_id}
                    {current.video_type && (
                      <span
                        style={{
                          marginLeft: 10,
                          fontSize: 13,
                          background: '#fff',
                          border: '2px solid #9f927d',
                          borderRadius: 50,
                          padding: '2px 10px',
                          color: '#794f27',
                        }}
                      >
                        {current.video_type}
                      </span>
                    )}
                    {fromCache && (
                      <span
                        style={{
                          marginLeft: 8,
                          fontSize: 13,
                          background: '#e6f9f6',
                          border: '2px solid #19c8b9',
                          borderRadius: 50,
                          padding: '2px 10px',
                          color: '#11a89b',
                        }}
                      >
                        ⚡ 來自快取
                      </span>
                    )}
                  </h2>
                  {current.slides_path && (
                    <a href={pptUrl(current.video_id)} style={{ textDecoration: 'none' }}>
                      <Button size="small" type="primary">
                        ⬇️ 下載投影片
                      </Button>
                    </a>
                  )}
                </div>
                <Divider type="wave-yellow" />

                {current.youtube_id && (
                  <div style={{ marginTop: 16 }}>
                    <YouTubePlayer
                      key={current.youtube_id}
                      videoId={current.youtube_id}
                      onReady={handlePlayerReady}
                    />
                  </div>
                )}

                <div style={{ marginTop: 8 }}>
                  <Tabs
                    items={[
                      {
                        key: 'summary',
                        label: '📝 重點摘要',
                        children: (
                          <div
                            className="markdown-body"
                            style={{
                              background: '#fff',
                              border: '3px solid #9f927d',
                              borderRadius: 18,
                              padding: '20px 24px',
                              color: '#725d42',
                              lineHeight: 1.7,
                            }}
                          >
                            <ReactMarkdown
                              components={{
                                li: ({ children }: any) => (
                                  <li>{renderWithSeek(children, seekTo)}</li>
                                ),
                                p: ({ children }: any) => (
                                  <p>{renderWithSeek(children, seekTo)}</p>
                                ),
                              }}
                            >
                              {current.summary_md}
                            </ReactMarkdown>
                          </div>
                        ),
                      },
                      {
                        key: 'transcript',
                        label: '📃 逐字稿',
                        children: (
                          <div
                            style={{
                              background: '#fff',
                              border: '3px solid #9f927d',
                              borderRadius: 18,
                              padding: '16px 20px',
                            }}
                          >
                            <TranscriptPanel videoId={current.video_id} onSeek={seekTo} />
                          </div>
                        ),
                      },
                      {
                        key: 'mermaid',
                        label: '🗺️ 知識圖譜',
                        children: (
                          <div
                            style={{
                              background: '#fff',
                              border: '3px solid #9f927d',
                              borderRadius: 18,
                              padding: '20px 24px',
                            }}
                          >
                            <MermaidPanel videoId={current.video_id} />
                          </div>
                        ),
                      },
                    ]}
                    defaultActiveKey="summary"
                  />
                </div>
              </Card>
            )}

            {/* Chat page */}
            {currentPage === 'chat' && current && (
              <Card
                color="app-orange"
                style={{
                  minHeight: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  boxSizing: 'border-box',
                }}
              >
                <h2 style={{ fontSize: '24px', color: '#fff', margin: '0 0 12px 0' }}>
                  💬 與島民秘書對話：{current.title}
                </h2>
                <Divider type="line-white" />

                <div
                  style={{
                    flex: 1,
                    background: 'rgba(255,255,255,0.8)',
                    border: '3px solid #9f927d',
                    borderRadius: 18,
                    padding: '20px',
                    margin: '20px 0',
                    overflowY: 'auto',
                  }}
                >
                  {chatMessages.map((msg, index) => (
                    <div key={msg.id} style={{ marginBottom: '16px' }}>
                      {msg.sender === 'secretary' ? (
                        <div style={{ color: '#725d42', fontSize: '15px', lineHeight: 1.6 }}>
                          <strong>秘書：</strong>
                          <span style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</span>
                          {msg.citations && msg.citations.length > 0 && (
                            <div
                              style={{
                                display: 'flex',
                                flexWrap: 'wrap',
                                gap: 6,
                                marginTop: 8,
                              }}
                            >
                              {msg.citations.map((c, i) => (
                                <button
                                  key={i}
                                  type="button"
                                  className="cite-chip"
                                  title={c.quote}
                                  onClick={() => seekTo(c.start)}
                                >
                                  🔖 {c.timestamp} · {c.quote}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      ) : (
                        <div
                          style={{
                            color: '#11a89b',
                            fontSize: '15px',
                            lineHeight: 1.6,
                            textAlign: 'right',
                          }}
                        >
                          <strong>你：</strong>
                          <span style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</span>
                        </div>
                      )}
                      {index < chatMessages.length - 1 && (
                        <hr style={{ border: '1px dashed #9f927d', margin: '12px 0' }} />
                      )}
                    </div>
                  ))}
                  {chatSending && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#725d42' }}>
                      <Loading active /> 秘書思考中...
                    </div>
                  )}
                  <div ref={chatBottomRef} />
                </div>

                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                  <div style={{ flex: 1 }}>
                    <Input
                      size="large"
                      placeholder="針對這部影片提問..."
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                      disabled={chatSending}
                    />
                  </div>
                  <Button size="large" onClick={handleSendMessage} disabled={chatSending}>
                    發送
                  </Button>
                </div>
              </Card>
            )}

            {/* Empty states for map/chat with no video */}
            {((currentPage === 'map' || currentPage === 'chat') && !current) && (
              <Card type="dashed" style={{ minHeight: '100%' }}>
                <div style={{ textAlign: 'center', padding: '60px 0', color: '#9f927d' }}>
                  尚未選擇影片,請先「➕ 提取新影片」或從左側歷史清單挑選。
                </div>
              </Card>
            )}
          </main>
        </div>
      </div>

      <Modal
        open={isModalOpen}
        title="廣播廣播！"
        onClose={() => setIsModalOpen(false)}
        onOk={() => setIsModalOpen(false)}
      >
        大家早安！秘書已經就位，隨時可以為您解讀影片囉！
      </Modal>

      <Modal
        open={settingsOpen}
        title="⚙️ 設定"
        onClose={() => setSettingsOpen(false)}
        onOk={saveSettings}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {requiresKey && !hasKey && (
            <div
              style={{
                background: '#fff4d6',
                border: '2px solid #e0a92e',
                borderRadius: 10,
                padding: '10px 12px',
                fontSize: 13,
                color: '#794f27',
              }}
            >
              此服務未內建 API 金鑰，請輸入你自己的 Google Gemini API key 才能使用摘要與問答功能。
            </div>
          )}

          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontWeight: 700, color: '#794f27', fontSize: 14 }}>
              Google Gemini API 金鑰
            </span>
            <Input
              type="password"
              placeholder="AIza..."
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              allowClear
              onClear={() => setApiKeyInput('')}
            />
            <span style={{ fontSize: 12, color: '#998a6f' }}>
              金鑰只會儲存在你的瀏覽器（localStorage），每次請求才隨標頭送出。可至{' '}
              <a
                href="https://aistudio.google.com/apikey"
                target="_blank"
                rel="noreferrer"
                style={{ color: '#11a89b' }}
              >
                Google AI Studio
              </a>{' '}
              免費取得。
            </span>
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontWeight: 700, color: '#794f27', fontSize: 14 }}>
              後端 API 網址
            </span>
            <Input
              placeholder="http://localhost:8000"
              value={apiUrlInput}
              onChange={(e) => setApiUrlInput(e.target.value)}
              allowClear
              onClear={() => setApiUrlInput('')}
            />
            <span style={{ fontSize: 12, color: '#998a6f' }}>
              留空則使用預設：{API_URL}
            </span>
          </label>
        </div>
      </Modal>
    </div>
  );
}
