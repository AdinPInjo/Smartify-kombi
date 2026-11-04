// Debug mode (Settings → Troubleshooting): detailed logs for a while.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMode } from "@/api/hooks";

export interface DebugState {
  enabled: boolean;
  until: number | null;
}

export function useDebugMode() {
  const { cloud, ready } = useMode();
  return useQuery({
    queryKey: ["debug"],
    queryFn: () => api.get<DebugState>("/system/debug"),
    refetchInterval: 60_000,
    enabled: ready && !cloud,
  });
}

export function useSetDebugMode() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { enabled: boolean; hours?: number }) => api.post<DebugState>("/system/debug", body),
    onSuccess: (data) => client.setQueryData(["debug"], data),
  });
}
