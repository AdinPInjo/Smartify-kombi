import { useMode } from "@/api/hooks";
import { ago } from "@/lib/format";
import { useNow } from "@/lib/useNow";

/** On the remote dashboard: is the van online, and how fresh is the data? */
export function RemoteBanner() {
  const { cloud, device } = useMode();
  useNow(10_000);
  if (!cloud) return null;
  const online = device?.online;
  return (
    <div className="chip" style={{ alignSelf: "flex-start", whiteSpace: "normal" }} role="status">
      <span className={`dot ${online ? "ok" : "bad"}`} />
      {online
        ? `Remote · van online · synced ${ago(device?.last_seen)}`
        : `Remote · van offline${device?.last_seen ? ` since ${ago(device.last_seen).replace(" ago", "")}` : ""} · changes wait for it`}
    </div>
  );
}

export function OnlyOnVan({ what }: { what: string }) {
  return <p className="small muted" style={{ margin: 0 }}>{what} is only available on the van's own dashboard (connect to its WiFi).</p>;
}
