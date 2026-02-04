import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type DbIntegrityStatus = {
  ok: boolean;
  status: string;
  message: string;
  result: string;
  db_path: string;
  last_run_ts: number | null;
};

const fetchDbIntegrity = async (): Promise<DbIntegrityStatus> => {
  const res = await fetch("/api/health/db-integrity");
  if (!res.ok) {
    throw new Error("Failed to load DB integrity status");
  }
  return res.json();
};

const formatTimestamp = (ts: number | null) => {
  if (!ts) return "Never";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return String(ts);
  }
};

export default function DbIntegrityDashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dbIntegrityStatus"],
    queryFn: fetchDbIntegrity,
    refetchInterval: 60_000,
  });

  const status = data?.status ?? "unknown";
  const ok = data?.ok ?? false;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100">DB Integrity</h1>
          <p className="text-sm text-zinc-400">
            Weekly database health check status and latest output.
          </p>
        </div>
        <Badge
          className={
            ok
              ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
              : "bg-rose-500/15 text-rose-300 border border-rose-500/30"
          }
        >
          {status.toUpperCase()}
        </Badge>
      </div>

      <Card className="border-zinc-800/60 bg-zinc-950/40 backdrop-blur">
        <CardHeader>
          <CardTitle className="text-base text-zinc-200">Latest Check</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-zinc-300">
          {isLoading && <div className="text-zinc-400">Loading status…</div>}
          {error && (
            <div className="text-rose-300">
              Failed to load status. Check backend logs.
            </div>
          )}
          {!isLoading && !error && (
            <>
              <div className="flex items-center justify-between">
                <span className="text-zinc-400">Last run</span>
                <span>{formatTimestamp(data?.last_run_ts ?? null)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-zinc-400">DB path</span>
                <span className="truncate max-w-[60%] text-right">{data?.db_path}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-zinc-400">Message</span>
                <span>{data?.message || "—"}</span>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card className="border-zinc-800/60 bg-zinc-950/40 backdrop-blur">
        <CardHeader>
          <CardTitle className="text-base text-zinc-200">Raw Output</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="max-h-80 overflow-auto rounded-lg bg-secondary/40 p-4 text-xs text-foreground border border-glass backdrop-blur-xl">
{data?.result || "No output recorded yet."}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
