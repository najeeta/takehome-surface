import { useState, useCallback, useRef } from "react";
import type { Source } from "../components/SourcePanel";
import type { ChatMessage } from "../components/ChatThread";

export type StreamStatus = "idle" | "connecting" | "retrieving" | "generating" | "done" | "error";

export function useStreamingChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [latestSources, setLatestSources] = useState<Source[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async (question: string) => {
    const userMsg: ChatMessage = { role: "user", content: question };
    setMessages(prev => [...prev, userMsg, { role: "assistant", content: "" }]);
    setStatus("connecting");
    setLatestSources([]);

    const abortController = new AbortController();
    abortRef.current = abortController;

    try {
      const response = await fetch("/ask/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        signal: abortController.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`API error: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let accumulatedText = "";
      let accumulatedSources: Source[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          if (!part.trim()) continue;

          let eventType = "message";
          const dataLines: string[] = [];

          for (const line of part.split("\n")) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7);
            } else if (line.startsWith("data: ")) {
              dataLines.push(line.slice(6));
            }
          }
          const data = dataLines.join("\n");

          switch (eventType) {
            case "delta":
              accumulatedText += JSON.parse(data);
              setMessages(prev => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: accumulatedText,
                };
                return updated;
              });
              break;

            case "source": {
              const source = JSON.parse(data) as Source;
              accumulatedSources = [...accumulatedSources, source];
              setLatestSources(accumulatedSources);
              break;
            }

            case "status": {
              const statusData = JSON.parse(data);
              setStatus(statusData.step as StreamStatus);
              break;
            }

            case "done":
              setStatus("idle");
              break;

            case "error": {
              const err = JSON.parse(data);
              setMessages(prev => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: `Sorry, something went wrong: ${err.detail}`,
                };
                return updated;
              });
              setStatus("error");
              break;
            }
          }
        }
      }

      if (status !== "error") setStatus("idle");
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setStatus("idle");
        return;
      }
      setMessages(prev => {
        const updated = [...prev];
        if (updated[updated.length - 1]?.role === "assistant") {
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: `Sorry, something went wrong: ${err instanceof Error ? err.message : "Unknown error"}`,
          };
        }
        return updated;
      });
      setStatus("error");
    }
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setStatus("idle");
  }, []);

  return { messages, latestSources, status, sendMessage, cancel };
}
