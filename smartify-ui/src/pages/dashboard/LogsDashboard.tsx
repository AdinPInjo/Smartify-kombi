import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, RefreshCw } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/utils";

type LogsPayload = {
  ok: boolean;
  lines: string[];
  path: string;
  error?: string;
};

export default function LogsDashboard() {
  const [lines, setLines] = useState(200);

  const { data, refetch, isFetching } = useQuery<LogsPayload>({
    queryKey: ["logs", "recent", lines],
    queryFn: async () => {
      const r = await apiFetch(`/api/logs/recent?lines=${lines}`, { cache: "no-store" });
      if (!r.ok) throw new Error(`Logs API returned ${r.status}`);
      return (await r.json()) as LogsPayload;
    },
    refetchInterval: 5000,
    retry: 1,
  });

  return (
    <div className="space-y-6">
      <Card className="glass-card p-0">
        <CardHeader className="pb-2 px-4 pt-4">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/20 border border-glass">
              <FileText className="h-4 w-4 text-primary" />
            </div>
            System Logs
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 px-4 pb-4 pt-0">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs text-muted-foreground">
              Showing last {lines} lines
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setLines(200)}
                className={lines === 200 ? "bg-primary/20 border-primary/40" : ""}
              >
                200
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setLines(500)}
                className={lines === 500 ? "bg-primary/20 border-primary/40" : ""}
              >
                500
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setLines(1000)}
                className={lines === 1000 ? "bg-primary/20 border-primary/40" : ""}
              >
                1000
              </Button>
              <Button size="sm" onClick={() => refetch()} disabled={isFetching}>
                <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
              </Button>
            </div>
          </div>

          <div className="rounded-xl border border-glass bg-secondary/30 p-3">
            {data?.error ? (
              <div className="text-sm text-warning">Error: {data.error}</div>
            ) : (
              <pre className="max-h-[60vh] overflow-auto text-xs leading-relaxed whitespace-pre-wrap">
                {(data?.lines ?? []).join("\n") || "No logs yet"}
              </pre>
            )}
          </div>
          <div className="text-xs text-muted-foreground">
            Source: {data?.path ?? "—"}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
