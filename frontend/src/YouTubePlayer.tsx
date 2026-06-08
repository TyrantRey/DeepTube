import { useEffect, useRef, useState } from 'react';

// Load the YouTube IFrame Player API exactly once; resolve when window.YT is
// ready. Rejects on script-load failure (CSP, ad blocker, offline) or after a
// timeout so callers can show a fallback instead of hanging forever. On failure
// the cached promise is cleared so a later mount can retry the load.
let apiPromise: Promise<any> | null = null;
const API_LOAD_TIMEOUT_MS = 15000;

function loadYouTubeApi(): Promise<any> {
  if (apiPromise) return apiPromise;
  apiPromise = new Promise((resolve, reject) => {
    const w = window as any;
    if (w.YT && w.YT.Player) {
      resolve(w.YT);
      return;
    }

    let settled = false;
    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      apiPromise = null; // let a later mount retry from scratch
      reject(new Error(message));
    };
    const timer = setTimeout(
      () => fail('YouTube IFrame API load timed out'),
      API_LOAD_TIMEOUT_MS,
    );

    const prev = w.onYouTubeIframeAPIReady;
    w.onYouTubeIframeAPIReady = () => {
      if (typeof prev === 'function') prev();
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(w.YT);
    };

    if (!document.getElementById('yt-iframe-api')) {
      const tag = document.createElement('script');
      tag.id = 'yt-iframe-api';
      tag.src = 'https://www.youtube.com/iframe_api';
      tag.onerror = () => {
        tag.remove();
        fail('Failed to load the YouTube IFrame API');
      };
      document.head.appendChild(tag);
    }
  });
  return apiPromise;
}

interface YouTubePlayerProps {
  videoId: string;
  onReady?: (player: any) => void;
}

/**
 * Embedded YouTube player. Mount with `key={videoId}` so a new video remounts a
 * fresh player. The player instance (with seekTo/playVideo) is handed up via
 * onReady. The YT-controlled iframe lives in an imperatively-appended child so
 * React never fights the API over the same DOM node.
 */
export function YouTubePlayer({ videoId, onReady }: YouTubePlayerProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    // `failed` resets on its own: the component is mounted with key={videoId},
    // so a new video fully remounts with the initial state.
    let cancelled = false;
    let player: any = null;

    loadYouTubeApi()
      .then((YT) => {
        if (cancelled || !wrapperRef.current) return;
        const host = document.createElement('div');
        host.style.width = '100%';
        host.style.height = '100%';
        wrapperRef.current.appendChild(host);
        player = new YT.Player(host, {
          videoId,
          playerVars: { rel: 0, modestbranding: 1 },
          events: {
            onReady: (e: any) => {
              if (!cancelled) onReady?.(e.target);
            },
          },
        });
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      try {
        player?.destroy();
      } catch {
        /* already gone */
      }
      if (wrapperRef.current) wrapperRef.current.innerHTML = '';
    };
    // onReady intentionally omitted: the player is recreated per videoId only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  return (
    <div
      style={{
        width: '100%',
        maxWidth: 680,
        margin: '0 auto 16px',
        aspectRatio: '16 / 9',
        border: '3px solid #9f927d',
        borderRadius: 18,
        overflow: 'hidden',
        background: '#000',
      }}
    >
      {failed ? (
        <a
          href={`https://www.youtube.com/watch?v=${videoId}`}
          target="_blank"
          rel="noreferrer"
          style={{
            display: 'flex',
            width: '100%',
            height: '100%',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 16,
            textAlign: 'center',
            color: '#fff',
            textDecoration: 'underline',
          }}
        >
          無法載入 YouTube 播放器，點此前往 YouTube 觀看
        </a>
      ) : (
        <div ref={wrapperRef} style={{ width: '100%', height: '100%' }} />
      )}
    </div>
  );
}
