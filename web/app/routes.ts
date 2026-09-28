import { type RouteConfig } from "@react-router/dev/routes";

export default [
  { path: "/", file: "routes/chat.tsx" },
  { path: "/ask/stream", file: "routes/ask-stream.tsx" },
] satisfies RouteConfig;
