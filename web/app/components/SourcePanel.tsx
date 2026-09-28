export interface Source {
  section_path: string;
  source_md_path: string;
  pages: string;
  links: { anchor_text: string; url: string }[];
  excerpt: string;
}

interface SourcePanelProps {
  sources: Source[];
}

function CitationCard({ source, index }: { source: Source; index: number }) {
  return (
    <div style={{
      background: 'var(--color-bg)',
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-md)',
      padding: 'var(--space-4)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-3)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 22,
          height: 22,
          borderRadius: '50%',
          background: 'var(--color-accent)',
          color: 'white',
          fontSize: 'var(--text-xs)',
          fontWeight: 'var(--font-weight-semibold)',
          flexShrink: 0,
        }}>
          {index + 1}
        </span>
        <span style={{
          fontSize: 'var(--text-sm)',
          fontWeight: 'var(--font-weight-semibold)',
          color: 'var(--color-text-primary)',
          lineHeight: 1.3,
        }}>
          {source.section_path}
        </span>
      </div>

      <div style={{
        display: 'flex',
        gap: 'var(--space-3)',
        fontSize: 'var(--text-xs)',
        color: 'var(--color-text-tertiary)',
      }}>
        <span>p. {source.pages}</span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {source.source_md_path.split('/').pop()}
        </span>
      </div>

      <p style={{
        margin: 0,
        fontSize: 'var(--text-sm)',
        color: 'var(--color-text-secondary)',
        lineHeight: 1.5,
        display: '-webkit-box',
        WebkitLineClamp: 4,
        WebkitBoxOrient: 'vertical',
        overflow: 'hidden',
      }}>
        {source.excerpt}
      </p>

      {source.links.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
          {source.links.map((link, i) => (
            <a
              key={i}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--color-accent)',
                textDecoration: 'none',
              }}
            >
              {link.anchor_text}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export function SourcePanel({ sources }: SourcePanelProps) {
  if (sources.length === 0) return null;

  return (
    <aside style={{
      background: 'var(--color-surface)',
      borderLeft: '1px solid var(--color-border)',
      width: 'var(--source-panel-width)',
      padding: 'var(--space-4)',
      overflowY: 'auto',
      height: '100%',
      flexShrink: 0,
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-3)',
    }}>
      <h3 style={{
        margin: 0,
        fontSize: 'var(--text-sm)',
        fontWeight: 'var(--font-weight-semibold)',
        color: 'var(--color-text-secondary)',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
      }}>
        Citations ({sources.length})
      </h3>
      {sources.map((source, i) => (
        <CitationCard key={i} source={source} index={i} />
      ))}
    </aside>
  );
}
