import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type { AuthUser } from "../api/types";

async function fetchMe(): Promise<AuthUser | null> {
  try {
    return await api.me();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null; // anonymous
    throw e;
  }
}

/** Current session (null = anonymous). Cached 5 min; login/logout invalidate it. */
export function useAuth() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchMe,
    staleTime: 300_000,
    retry: false,
  });
}
