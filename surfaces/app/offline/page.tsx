/**
 * Offline fallback, served by the service worker when a navigation fails.
 *
 * Deliberately does not show a cached balance. Showing someone a stale figure
 * they might act on is worse than telling them the truth.
 */
export default function OfflinePage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
      <div className="max-w-sm text-center">
        <h1 className="text-lg font-bold text-heading">You are offline</h1>
        <p className="mt-2 text-sm text-muted">
          CowriePay needs a connection to show your balance and move money. Nothing you started has
          been lost — any transfer already in flight either completes or refunds itself.
        </p>
      </div>
    </div>
  );
}
