/** Error card for a failed query, with a retry action wired to `refetch`. */
export function QueryError({
  message = "Something went wrong loading this data.",
  onRetry,
}: {
  message?: string;
  onRetry: () => void;
}) {
  return (
    <div className="card text-center">
      <p className="text-sm text-red-600 dark:text-red-400">{message}</p>
      <button type="button" className="btn-secondary mt-3" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
