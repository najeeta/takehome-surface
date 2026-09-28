import { useRef, useEffect } from "react";
import { Message } from "./Message";
import type { Source } from "./SourcePanel";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
}

interface ChatThreadProps {
  messages: ChatMessage[];
}

export function ChatThread({ messages }: ChatThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      padding: 'var(--space-6)',
      maxWidth: 'var(--chat-max-width)',
      margin: '0 auto',
      width: '100%',
    }}>
      {messages.length === 0 && (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          color: 'var(--color-text-tertiary)',
          gap: 'var(--space-3)',
        }}>
          <p style={{ fontSize: 'var(--text-lg)', margin: 0 }}>Ask a question about the PostHog handbook</p>
          <p style={{ fontSize: 'var(--text-sm)', margin: 0 }}>Answers are grounded in the handbook with citations</p>
        </div>
      )}
      {messages.map((msg, i) => (
        <Message key={i} role={msg.role} content={msg.content} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
