export function Header() {
  return (
    <header style={{
      background: 'var(--color-bg)',
      borderBottom: '1px solid var(--color-border)',
      padding: 'var(--space-4) var(--space-6)',
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-3)',
    }}>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" stroke="var(--color-accent)" strokeWidth="2" />
        <circle cx="12" cy="12" r="4" fill="var(--color-accent)" />
      </svg>
      <h1 style={{
        margin: 0,
        fontSize: 'var(--text-lg)',
        fontWeight: 'var(--font-weight-semibold)',
        color: 'var(--color-text-primary)',
      }}>
        Surface
      </h1>
      <span style={{
        fontSize: 'var(--text-sm)',
        color: 'var(--color-text-secondary)',
      }}>
        Handbook Q&A
      </span>
    </header>
  );
}
