import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'loose',
  theme: 'base',
  themeVariables: {
    primaryColor: '#e6f9f6',
    primaryBorderColor: '#19c8b9',
    primaryTextColor: '#725d42',
    lineColor: '#9f927d',
    fontFamily: 'Nunito, "Noto Sans SC", sans-serif',
  },
});

let _seq = 0;

interface MermaidProps {
  code: string;
}

/** Render Mermaid source to SVG; falls back to showing the raw source on a
 *  syntax error so an invalid diagram never blanks the page. */
export function Mermaid({ code }: MermaidProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const id = `mermaid-svg-${_seq++}`;
    mermaid
      .render(id, code)
      .then(({ svg }) => {
        if (cancelled) return;
        if (ref.current) ref.current.innerHTML = svg;
        setError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <div>
        <p style={{ color: '#e05a5a', fontWeight: 700, marginBottom: 8 }}>
          ⚠️ 圖譜語法無法解析，以下為原始 Mermaid 內容：
        </p>
        <pre
          style={{
            background: '#fffdf0',
            border: '2px solid #e1dacb',
            borderRadius: 12,
            padding: 16,
            overflowX: 'auto',
            whiteSpace: 'pre-wrap',
            color: '#725d42',
          }}
        >
          {code}
        </pre>
      </div>
    );
  }

  return (
    <div
      ref={ref}
      style={{ display: 'flex', justifyContent: 'center', overflowX: 'auto' }}
    />
  );
}
