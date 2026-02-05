import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { GripVertical, LayoutGrid, RefreshCcw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  DEFAULT_OVERVIEW_LAYOUT,
  OVERVIEW_MODULES,
  OverviewLayoutConfig,
  OverviewModuleId,
  getOverviewLayout,
  resetOverviewLayout,
  setOverviewLayout,
} from "@/lib/overviewLayout";

const OverviewLayoutSettings = () => {
  const [layout, setLayout] = useState<OverviewLayoutConfig>(DEFAULT_OVERVIEW_LAYOUT);
  const [dragging, setDragging] = useState<{ id: OverviewModuleId; zone: "top" | "bottom" } | null>(null);

  useEffect(() => {
    setLayout(getOverviewLayout());
  }, []);

  const hiddenSet = useMemo(() => new Set(layout.hidden), [layout.hidden]);

  const updateLayout = (next: OverviewLayoutConfig) => {
    setLayout(next);
    setOverviewLayout(next);
  };

  const toggleModule = (id: OverviewModuleId) => {
    const hidden = new Set(layout.hidden);
    if (hidden.has(id)) {
      hidden.delete(id);
    } else {
      hidden.add(id);
    }
    updateLayout({ ...layout, hidden: Array.from(hidden) as OverviewModuleId[] });
  };

  const setColumns = (cols: 3 | 4 | 5) => {
    updateLayout({ ...layout, columns: cols });
  };

  const moveByDrop = (activeId: OverviewModuleId, overId: OverviewModuleId, zone: "top" | "bottom") => {
    if (activeId === overId) return;
    const list = zone === "top" ? [...layout.topOrder] : [...layout.bottomOrder];
    const from = list.indexOf(activeId);
    const to = list.indexOf(overId);
    if (from < 0 || to < 0) return;
    list.splice(from, 1);
    list.splice(to, 0, activeId);
    updateLayout({
      ...layout,
      topOrder: zone === "top" ? list : layout.topOrder,
      bottomOrder: zone === "bottom" ? list : layout.bottomOrder,
    });
  };

  const renderList = (zone: "top" | "bottom") => {
    const ids = zone === "top" ? layout.topOrder : layout.bottomOrder;
    const items = ids.map((id) => OVERVIEW_MODULES.find((m) => m.id === id)).filter(Boolean);

    return (
      <div className="space-y-3">
        {items.map((item, idx) => {
          if (!item) return null;
          const disabled = hiddenSet.has(item.id);
          return (
            <div
              key={item.id}
              className={[
                "flex flex-col gap-3 rounded-xl border border-glass bg-secondary/30 px-4 py-3 backdrop-blur-xl transition-all",
                dragging?.id === item.id ? "opacity-60 ring-2 ring-primary/40" : "",
              ].join(" ")}
              draggable
              onDragStart={() => setDragging({ id: item.id, zone })}
              onDragEnd={() => setDragging(null)}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
              }}
              onDrop={() => {
                if (!dragging || dragging.zone !== zone) return;
                moveByDrop(dragging.id, item.id, zone);
                setDragging(null);
              }}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2 text-blue-300">
                    <GripVertical className="h-4 w-4" />
                    <LayoutGrid className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-zinc-100">{item.label}</div>
                    <div className="text-xs text-zinc-400">{zone === "top" ? "Top grid" : "Bottom grid"}</div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <Switch checked={!disabled} onCheckedChange={() => toggleModule(item.id)} />
                </div>
              </div>

              <div className="text-xs text-zinc-500">
                {disabled ? "Hidden on overview" : "Visible on overview"}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100">Overview Layout</h1>
          <p className="text-sm text-zinc-400">
            Reorder and toggle modules for the overview dashboard.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={() => resetOverviewLayout()}>
            <RefreshCcw className="h-4 w-4" />
            Reset to default
          </Button>
          <Button variant="ghost" asChild>
            <Link to="/dashboard/settings">Back to Settings</Link>
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Grid Columns</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant={layout.columns === 3 ? "default" : "outline"}
              onClick={() => setColumns(3)}
            >
              3 Columns
            </Button>
            <Button
              variant={layout.columns === 4 ? "default" : "outline"}
              onClick={() => setColumns(4)}
            >
              4 Columns
            </Button>
            <Button
              variant={layout.columns === 5 ? "default" : "outline"}
              onClick={() => setColumns(5)}
            >
              5 Columns
            </Button>
            <p className="text-xs text-muted-foreground">
              Smaller cards look better on large screens with 4–5 columns.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top Grid</CardTitle>
        </CardHeader>
        <CardContent>{renderList("top")}</CardContent>
      </Card>

      {/* Bottom grid removed: all modules are now in the top grid */}
    </div>
  );
};

export default OverviewLayoutSettings;
