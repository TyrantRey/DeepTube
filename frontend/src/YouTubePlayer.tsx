import { useEffect, useRef } from 'react';

// Load the YouTube IFrame Player API exactly once; resolve when window.YT is ready.
let apiPromise: Promise<any> | null = null;

function loadYouTubeApi(): Promise<any> {
  if (apiPromise) return apiPromise;
  apiPromise = new Promise((resolve) => {
    const w = window as any;
    if (w.YT && w.YT.Player) {
      resolve(w.YT);
      return;
    }
    const prev = w.onYouTubeIframeAPIReady;
    w.onYouTubeIframeAPIReady = () => {
      if (typeof prev === 'function') prev();
      resolve(w.YT);
    };
    if (!document.getElementById('yt-iframe-api')) {
      const tag = document.createElement('script');
      tag.id = 'yt-iframe-api';
      tag.src = 'https://www.youtube.com/iframe_api';
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

  useEffect(() => {
    let cancelled = false;
    let player: any = null;

    loadYouTubeApi().then((YT) => {
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
      <div ref={wrapperRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}
