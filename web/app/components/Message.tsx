import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MessageProps {
  role: "user" | "assistant";
  content: string;
}

export function Message({ role, content }: MessageProps) {
  const isUser = role === "user";

  return (
    <div style={{
      display: 'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      padding: 'var(--space-2) 0',
    }}>
      <div style={{
        maxWidth: isUser ? '80%' : '100%',
        background: isUser ? 'var(--color-accent-muted)' : 'transparent',
        border: isUser ? '1px solid rgba(99, 102, 241, 0.15)' : 'none',
        borderRadius: 'var(--radius-md)',
        padding: isUser ? 'var(--space-3) var(--space-4)' : 'var(--space-3) 0',
      }}>
        {isUser ? (
          <p style={{
            margin: 0,
            fontSize: 'var(--text-base)',
            fontFamily: 'var(--font-sans)',
            color: 'var(--color-text-primary)',
            lineHeight: 1.6,
          }}>
            {content}
          </p>
        ) : (
          <div className="markdown-body">
            <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
          </div>
        )}
      </div>
    </div>
  );
}
