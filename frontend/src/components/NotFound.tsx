import { Link } from "@tanstack/react-router";

// Rendered inside the root route's Layout for any URL that matches no route.
export function NotFound() {
  return (
    <div className="card mx-auto max-w-md text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
        The page you're looking for doesn't exist or may have moved.
      </p>
      <div className="mt-4 flex justify-center gap-4 text-sm font-medium">
        <Link to="/" className="text-sky-700 hover:underline dark:text-sky-400">
          Dashboard
        </Link>
        <Link to="/notices" className="text-sky-700 hover:underline dark:text-sky-400">
          Notices
        </Link>
        <Link to="/states" className="text-sky-700 hover:underline dark:text-sky-400">
          Browse states
        </Link>
      </div>
    </div>
  );
}
