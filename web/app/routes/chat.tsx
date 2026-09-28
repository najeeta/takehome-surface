import { useRef } from "react";
import { Header } from "../components/Header";
import { ChatThread } from "../components/ChatThread";
import { SourcePanel } from "../components/SourcePanel";
import { useStreamingChat } from "../hooks/useStreamingChat";

export default function ChatPage() {
  const { messages, latestSources, status, sendMessage, cancel } = useStreamingChat();
  const formRef = useRef<HTMLFormElement>(null);

  const isStreaming = status !== "idle" && status !== "error";

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const question = new FormData(form).get("question") as string;
    if (!question.trim() || isStreaming) return;
    form.reset();
    sendMessage(question);
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      background: 'var(--color-bg)',
    }}>
      <Header />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
          <ChatThread messages={messages} />
          <div style={{
            borderTop: '1px solid var(--color-border)',
            padding: 'var(--space-4) var(--space-6)',
            background: 'var(--color-bg)',
          }}>
            <form
              ref={formRef}
              onSubmit={handleSubmit}
              style={{
                display: 'flex',
                gap: 'var(--space-3)',
                maxWidth: 'var(--chat-max-width)',
                margin: '0 auto',
              }}
            >
              <input
                name="question"
                type="text"
                placeholder="Ask about the PostHog handbook..."
                required
                disabled={isStreaming}
                autoComplete="off"
                style={{
                  flex: 1,
                  background: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-md)',
                  padding: 'var(--space-3) var(--space-4)',
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--text-base)',
                  color: 'var(--color-text-primary)',
                  outline: 'none',
                }}
                onFocus={e => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
                onBlur={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
              />
              {isStreaming ? (
                <button
                  type="button"
                  onClick={cancel}
                  style={{
                    background: 'var(--color-surface)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-sm)',
                    padding: 'var(--space-2) var(--space-4)',
                    fontFamily: 'var(--font-sans)',
                    fontSize: 'var(--text-sm)',
                    fontWeight: 'var(--font-weight-medium)',
                    color: 'var(--color-text-secondary)',
                    cursor: 'pointer',
                  }}
                >
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  style={{
                    background: 'var(--color-accent)',
                    border: 'none',
                    borderRadius: 'var(--radius-sm)',
                    padding: 'var(--space-2) var(--space-4)',
                    fontFamily: 'var(--font-sans)',
                    fontSize: 'var(--text-sm)',
                    fontWeight: 'var(--font-weight-medium)',
                    color: 'white',
                    cursor: 'pointer',
                  }}
                >
                  Send
                </button>
              )}
            </form>
            {(status === "connecting" || status === "retrieving") && (
              <p style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--color-text-tertiary)',
                marginTop: 'var(--space-2)',
                maxWidth: 'var(--chat-max-width)',
                margin: 'var(--space-2) auto 0',
              }}>
                {status === "retrieving" ? "Searching handbook..." : "Connecting..."}
              </p>
            )}
          </div>
        </div>
        <SourcePanel sources={latestSources} />
      </div>
    </div>
  );
}
