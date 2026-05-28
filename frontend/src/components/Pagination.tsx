interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (newOffset: number) => void;
}

export function Pagination({ total, limit, offset, onPageChange }: PaginationProps) {
  const current = Math.floor(offset / limit) + 1;
  const last = Math.max(1, Math.ceil(total / limit));
  if (last <= 1) return null;

  return (
    <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
      <span>
        Page {current} of {last} · {total.toLocaleString()} results
      </span>
      <div className="flex gap-2">
        <button
          className="btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={current === 1}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
        >
          ← Prev
        </button>
        <button
          className="btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={current >= last}
          onClick={() => onPageChange(offset + limit)}
        >
          Next →
        </button>
      </div>
    </div>
  );
}
