// Scenes: one tap switches several relays ("Night": heater auto, fan off).
// Stored on the van, so every phone, tablet and the remote dashboard share them.

import {
  BedDouble,
  Car,
  Coffee,
  DoorOpen,
  Flame,
  Moon,
  Pencil,
  Power,
  Snowflake,
  Star,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMode, useRelays } from "@/api/hooks";
import { useHeaters } from "./Heater";
import { Dialog, ErrorNote, Field, Segmented, useErrorToast, useToast } from "./ui";

type Action = "on" | "off" | "auto";

export interface Scene {
  id: number;
  name: string;
  icon: string;
  actions: Record<string, Action>;
  position: number;
  active: boolean;
}

const ICONS: Record<string, LucideIcon> = {
  moon: Moon,
  sun: Sun,
  door: DoorOpen,
  flame: Flame,
  snowflake: Snowflake,
  coffee: Coffee,
  bed: BedDouble,
  car: Car,
  power: Power,
  star: Star,
};

const MAX_SCENES = 8;

export const useScenes = () =>
  useQuery({
    queryKey: ["scenes"],
    queryFn: () => api.get<{ scenes: Scene[] }>("/scenes").then((r) => r.scenes),
    refetchInterval: 5_000,
  });

function summary(scene: Scene, names: Record<string, string>): string {
  return Object.entries(scene.actions)
    .map(([id, action]) => `${names[id] ?? id} ${action}`)
    .join(" · ");
}

function useRelayNames() {
  const relays = useRelays();
  const heaters = useHeaters();
  return Object.fromEntries([
    ...(relays.data ?? []).map((r) => [r.id, r.label || r.name]),
    ...(heaters.data?.heaters ?? []).map((h) => [`heater:${h.id}`, h.name]),
  ]) as Record<string, string>;
}

/** Big buttons that run a scene. `large` for the tablet panel. */
export function SceneButtons({ large = false }: { large?: boolean }) {
  const scenes = useScenes();
  const names = useRelayNames();
  const client = useQueryClient();
  const toast = useToast();
  const showError = useErrorToast();
  const { cloud } = useMode();
  const run = useMutation({
    mutationFn: (scene: Scene) => api.post<{ skipped: string[] }>(`/scenes/${scene.id}/run`),
    onSuccess: (result, scene) => {
      toast(cloud ? `${scene.name}: sent to the van` : result.skipped.length ? `${scene.name}: done (some switches no longer exist)` : `${scene.name}: done`);
      void client.invalidateQueries({ queryKey: ["relays"] });
      void client.invalidateQueries({ queryKey: ["scenes"] });
    },
    onError: showError,
  });

  if (scenes.data?.length === 0) {
    return (
      <p className="small muted" style={{ margin: 0 }}>
        No scenes yet. <Link to="/switches#scenes">Make one</Link>, e.g. “Night”: heater on its rules, fan off.
      </p>
    );
  }
  return (
    <div className={`scene-grid ${large ? "large" : ""}`}>
      {scenes.data?.map((scene) => {
        const Icon = ICONS[scene.icon] ?? Star;
        return (
          <button
            key={scene.id}
            type="button"
            className={`scene-button ${scene.active ? "active" : ""}`}
            aria-pressed={scene.active}
            disabled={run.isPending}
            onClick={() => run.mutate(scene)}
          >
            <Icon size={large ? 30 : 22} aria-hidden="true" />
            <span className="scene-name">{scene.name}</span>
            <span className="tiny muted scene-summary">{summary(scene, names)}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Switches page: list, make, change and delete scenes. */
export function ScenesCard() {
  const scenes = useScenes();
  const names = useRelayNames();
  const { cloud } = useMode();
  const [editing, setEditing] = useState<Scene | "new" | null>(null);
  const count = scenes.data?.length ?? 0;
  return (
    <section id="scenes" className="card" style={{ scrollMarginTop: 16 }}>
      <div className="row-between">
        <h2 className="label" style={{ margin: 0 }}>Scenes</h2>
        {!cloud && count < MAX_SCENES && (
          <button type="button" className="btn small" onClick={() => setEditing("new")}>
            New scene
          </button>
        )}
      </div>
      <span className="small muted">
        One tap switches several relays, e.g. “Night”: heater on its rules, fan off. They show up on the overview and the
        tablet panel.
      </span>
      {count > 0 && (
        <div className="list">
          {scenes.data?.map((scene) => {
            const Icon = ICONS[scene.icon] ?? Star;
            return (
              <div key={scene.id} className="row-between" style={{ gap: 10 }}>
                <span className="row" style={{ gap: 10, minWidth: 0 }}>
                  <Icon size={20} aria-hidden="true" className={scene.active ? "c-accent" : "muted"} />
                  <span className="stack" style={{ gap: 0, minWidth: 0 }}>
                    <strong>{scene.name}</strong>
                    <span className="tiny muted">{summary(scene, names)}</span>
                  </span>
                </span>
                {!cloud && (
                  <button type="button" className="btn small ghost" aria-label={`Edit ${scene.name}`} onClick={() => setEditing(scene)}>
                    <Pencil size={16} aria-hidden="true" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
      {cloud && <span className="tiny faint">Scenes are made on the van's own dashboard. Here you can run them.</span>}
      {editing && <SceneDialog scene={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </section>
  );
}

function SceneDialog({ scene, onClose }: { scene: Scene | null; onClose: () => void }) {
  const relays = useRelays();
  const heaters = useHeaters();
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(scene?.name ?? "");
  const [icon, setIcon] = useState(scene?.icon ?? "moon");
  const [actions, setActions] = useState<Record<string, Action | "keep">>(scene?.actions ?? {});
  const chosen = Object.fromEntries(Object.entries(actions).filter(([, a]) => a !== "keep")) as Record<string, Action>;

  const done = (message: string) => {
    void client.invalidateQueries({ queryKey: ["scenes"] });
    toast(message);
    onClose();
  };
  const save = useMutation({
    mutationFn: () =>
      scene
        ? api.patch<Scene>(`/scenes/${scene.id}`, { name, icon, actions: chosen })
        : api.post<Scene>("/scenes", { name, icon, actions: chosen }),
    onSuccess: () => done(scene ? "Scene saved" : "Scene made"),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/scenes/${scene?.id}`),
    onSuccess: () => done("Scene deleted"),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <Dialog title={scene ? "Edit scene" : "New scene"} onClose={onClose}>
      <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
        <Field label="Name">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={30} placeholder="Night" required />
        </Field>
        <div className="stack" style={{ gap: 6 }}>
          <span className="small muted">Icon</span>
          <div className="row wrap" style={{ gap: 6 }}>
            {Object.entries(ICONS).map(([key, Icon]) => (
              <button
                key={key}
                type="button"
                className={`dash-icon ${icon === key ? "selected" : ""}`}
                aria-label={key}
                aria-pressed={icon === key}
                onClick={() => setIcon(key)}
              >
                <Icon size={20} aria-hidden="true" />
              </button>
            ))}
          </div>
        </div>
        <div className="stack" style={{ gap: 10 }}>
          <span className="small muted">What it does</span>
          {relays.data?.map((relay) => (
            <div key={relay.id} className="stack" style={{ gap: 4 }}>
              <span>{relay.label || relay.name}</span>
              <Segmented<Action | "keep">
                label={`${relay.label || relay.name} in this scene`}
                value={actions[relay.id] ?? "keep"}
                onChange={(value) => setActions({ ...actions, [relay.id]: value })}
                options={[
                  { value: "keep", label: "Unchanged" },
                  { value: "on", label: "On" },
                  { value: "off", label: "Off" },
                  { value: "auto", label: "Auto" },
                ]}
              />
            </div>
          ))}
          {heaters.data?.heaters.map((heater) => {
            const key = `heater:${heater.id}`;
            return (
              <div key={key} className="stack" style={{ gap: 4 }}>
                <span>{heater.name} (diesel heater)</span>
                <Segmented<"keep" | "on" | "off">
                  label={`${heater.name} in this scene`}
                  value={(actions[key] as "on" | "off" | undefined) ?? "keep"}
                  onChange={(value) => setActions({ ...actions, [key]: value })}
                  options={[
                    { value: "keep", label: "Unchanged" },
                    { value: "on", label: "On" },
                    { value: "off", label: "Off" },
                  ]}
                />
              </div>
            );
          })}
          <span className="tiny faint">
            On and Off stay until you change them. Auto hands the switch back to its rules.
          </span>
        </div>
        <ErrorNote error={save.error ?? remove.error} />
        <div className="row-between">
          {scene ? (
            <button type="button" className="btn small danger" disabled={remove.isPending} onClick={() => window.confirm(`Delete “${scene.name}”?`) && remove.mutate()}>
              Delete
            </button>
          ) : (
            <span />
          )}
          <button type="submit" className="btn primary" disabled={save.isPending || !name.trim() || Object.keys(chosen).length === 0}>
            {save.isPending ? "Saving…" : "Save scene"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
