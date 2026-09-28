# Frontend Specification

Companion to [agent-api-spec.md](./agent-api-spec.md). Covers the React application, routing, layout, and design system.

---

## Stack

| Layer       | Choice                         | Reason                                    |
|-------------|--------------------------------|-------------------------------------------|
| Framework   | React Router v7 (SSR mode)     | Loader/action pattern, server rendering   |
| Styling     | Tailwind CSS v4               | Utility-first, fast to match design system |
| Runtime     | Node 22                        | LTS, native fetch                         |

### References

- React Router v7: https://reactrouter.com/home
- Loaders: https://reactrouter.com/how-to/data-loading
- Actions: https://reactrouter.com/how-to/actions
- SSR: https://reactrouter.com/how-to/ssr

---

## Routes

Single route. The loader hydrates any initial state, the action handles form submission to the API.

```
Route          Component        Loader              Action
/              ChatPage         none                POST /ask via API
```

### Route definition

```tsx
// app/routes.ts
import { type RouteConfig } from "@react-router/dev/routes";

export default [
  { path: "/", file: "routes/chat.tsx" },
] satisfies RouteConfig;
```

### Action (server-side)

The form submits to this action, which calls the FastAPI backend. Runs on the server — the API key and backend URL never reach the client.

```tsx
// app/routes/chat.tsx
import type { ActionFunctionArgs } from "react-router";

export async function action({ request }: ActionFunctionArgs) {
  const formData = await request.formData();
  const question = formData.get("question") as string;

  const res = await fetch(`${process.env.API_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  return await res.json();
}
```

---

## Layout

Two-panel layout. Chat thread on the left, source panel on the right. Source panel is hidden until a source is selected.

```
+-----------------------------------------------------------+
|  Header: logo + title                                      |
+---------------------------+-------------------------------+
|                           |                               |
|  Chat thread              |  Source panel                  |
|                           |                               |
|  [message]                |  Section path                 |
|  [message]                |  Source file                   |
|  [message]                |  Page range                    |
|     [source chip] ──────> |  Excerpt text                  |
|     [source chip]         |  Links                         |
|                           |                               |
|                           |                               |
+---------------------------+-------------------------------+
|  [message input]          [send]                           |
+-----------------------------------------------------------+
```

### Component tree

```
ChatPage
├── Header
├── main (two-panel)
│   ├── ChatThread
│   │   ├── Message (role=user)
│   │   └── Message (role=assistant)
│   │       └── SourceChip[] (clickable, opens source panel)
│   └── SourcePanel (conditional)
│       ├── section_path
│       ├── source_md_path
│       ├── pages
│       ├── excerpt
│       └── LinkList
└── MessageInput (form with action)
```

### Key behaviors

- **MessageInput** is a `<Form method="post">` — React Router handles submission via the action
- **Chat history** is client state (useState array of `{role, content, sources}`)
- On action response, append both the user message and the assistant response to the thread
- **SourceChip** is an inline pill in the assistant message showing `section_path (p.X)` — clicking it populates the SourcePanel
- **SourcePanel** slides in from the right or is always visible on desktop, hidden on mobile
- On mobile, SourcePanel renders as a bottom sheet or overlay

---

## Design System

Derived from the surface.ai brand identity.

### Colors

```css
:root {
  /* Core palette */
  --color-bg:            #0A0A0A;    /* near-black background */
  --color-surface:       #141414;    /* card/panel background */
  --color-surface-hover: #1E1E1E;    /* interactive hover */
  --color-border:        #2A2A2A;    /* subtle borders */

  /* Text */
  --color-text-primary:   #F5F5F5;   /* main body text */
  --color-text-secondary: #A0A0A0;   /* muted/supporting text */
  --color-text-tertiary:  #666666;   /* disabled/placeholder */

  /* Accent */
  --color-accent:        #6366F1;    /* indigo — primary action */
  --color-accent-hover:  #818CF8;    /* lighter on hover */
  --color-accent-muted:  #6366F11A;  /* 10% opacity for backgrounds */

  /* Semantic */
  --color-success:       #22C55E;
  --color-warning:       #EAB308;
  --color-error:         #EF4444;
}
```

### Typography

```css
:root {
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;

  --text-xs:   0.75rem;   /* 12px — chips, metadata */
  --text-sm:   0.875rem;  /* 14px — secondary text */
  --text-base: 1rem;      /* 16px — body, messages */
  --text-lg:   1.125rem;  /* 18px — section headers */
  --text-xl:   1.5rem;    /* 24px — page title */

  --font-weight-normal: 400;
  --font-weight-medium: 500;
  --font-weight-semibold: 600;
}
```

### Spacing & Layout

```css
:root {
  --radius-sm:  6px;
  --radius-md:  10px;
  --radius-lg:  16px;

  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-6:  24px;
  --space-8:  32px;

  /* Layout */
  --chat-max-width:  640px;
  --source-panel-width: 400px;
}
```

### Component Styles

**Message bubble (user)**
```
background: var(--color-accent-muted)
border: 1px solid var(--color-accent) at 20% opacity
border-radius: var(--radius-md)
padding: var(--space-3) var(--space-4)
font: var(--text-base) var(--font-sans)
color: var(--color-text-primary)
```

**Message bubble (assistant)**
```
background: transparent
border: none
padding: var(--space-3) 0
font: var(--text-base) var(--font-sans)
color: var(--color-text-primary)
```

**Source chip**
```
display: inline-flex
background: var(--color-surface)
border: 1px solid var(--color-border)
border-radius: var(--radius-sm)
padding: var(--space-1) var(--space-2)
font: var(--text-xs) var(--font-mono)
color: var(--color-text-secondary)
cursor: pointer
hover: border-color var(--color-accent)
```

**Source panel**
```
background: var(--color-surface)
border-left: 1px solid var(--color-border)
width: var(--source-panel-width)
padding: var(--space-6)
overflow-y: auto
```

**Message input**
```
background: var(--color-surface)
border: 1px solid var(--color-border)
border-radius: var(--radius-md)
padding: var(--space-3) var(--space-4)
font: var(--text-base) var(--font-sans)
color: var(--color-text-primary)
placeholder-color: var(--color-text-tertiary)
focus: border-color var(--color-accent)
```

**Send button**
```
background: var(--color-accent)
border-radius: var(--radius-sm)
padding: var(--space-2) var(--space-4)
font: var(--text-sm) var(--font-sans) var(--font-weight-medium)
color: white
hover: background var(--color-accent-hover)
```

**Header**
```
background: var(--color-bg)
border-bottom: 1px solid var(--color-border)
padding: var(--space-4) var(--space-6)
```

---

## Docker Compose Addition

```yaml
web:
  build: ./web
  depends_on:
    api:
      condition: service_started
  ports:
    - "3000:3000"
  environment:
    - API_URL=http://api:8000
```

---

## File Structure

```
surface/
  web/
    Dockerfile
    package.json
    react-router.config.ts
    app/
      root.tsx               # html shell, global styles, css vars
      routes.ts              # route config
      routes/
        chat.tsx             # action + ChatPage component
      components/
        Header.tsx
        ChatThread.tsx
        Message.tsx
        SourceChip.tsx
        SourcePanel.tsx
        MessageInput.tsx
      styles/
        tokens.css           # css custom properties (design system)
        app.css              # tailwind directives + overrides
  docs/
    data-model-spec.md
    agent-api-spec.md
    frontend-spec.md         # this file
```
