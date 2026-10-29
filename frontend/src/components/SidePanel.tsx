import { useRef, useState, type KeyboardEvent } from "react";
import type { AreasResult, StudyDetail } from "../api/types";
import AreasPanel from "./AreasPanel";
import RiskSummary from "./RiskSummary";
import SegmentationPanel from "./SegmentationPanel";
import VolumetryPanel, { LongitudinalPanel } from "./VolumetryPanel";
import "./sidepanel.css";

/**
 * Columna derecha con pestañas (§14, ticket F10): Volumetría · Segmentación · Áreas · Longitudinal.
 *
 * Patrón ARIA "tabs" con activación automática: flechas ←/→ (y Inicio/Fin) mueven el foco y seleccionan.
 * Todos los paneles quedan montados y los inactivos se ocultan con `hidden`, así un job de segmentación o de
 * áreas sigue sondeándose aunque el usuario cambie de pestaña.
 */

export type SideTab = "volumetria" | "segmentacion" | "areas" | "longitudinal";

export const SIDE_TABS: { id: SideTab; label: string }[] = [
  { id: "volumetria", label: "Volumetría" },
  { id: "segmentacion", label: "Segmentación" },
  { id: "areas", label: "Áreas" },
  { id: "longitudinal", label: "Longitudinal" },
];

interface Props {
  study: StudyDetail;
  tab: SideTab;
  onTabChange: (tab: SideTab) => void;
  areas: AreasResult | null;
  focusedLabel: number | null;
  onFocusLabel: (label: number | null) => void;
  onSegmentationCompleted: () => void;
  onAreasCompleted: (r: AreasResult) => void;
  onAreasLoaded: (r: AreasResult | null) => void;
}

export default function SidePanel({
  study,
  tab,
  onTabChange,
  areas,
  focusedLabel,
  onFocusLabel,
  onSegmentationCompleted,
  onAreasCompleted,
  onAreasLoaded,
}: Props) {
  const tabRefs = useRef<Partial<Record<SideTab, HTMLButtonElement | null>>>({});
  const [segBusy, setSegBusy] = useState(false);
  const [areasBusy, setAreasBusy] = useState(false);
  const busy: Partial<Record<SideTab, boolean>> = { segmentacion: segBusy, areas: areasBusy };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = SIDE_TABS.findIndex((t) => t.id === tab);
    let next: number | null = null;
    if (e.key === "ArrowRight") next = (i + 1) % SIDE_TABS.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + SIDE_TABS.length) % SIDE_TABS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = SIDE_TABS.length - 1;
    if (next === null) return;
    e.preventDefault();
    const id = SIDE_TABS[next].id;
    onTabChange(id);
    tabRefs.current[id]?.focus();
  };

  const panelProps = (id: SideTab) => ({
    id: `sidepanel-${id}`,
    role: "tabpanel" as const,
    "aria-labelledby": `sidetab-${id}`,
    hidden: tab !== id,
    tabIndex: 0,
    className: "sidepanel-panel",
  });

  return (
    <div className="sidepanel">
      <div className="sidepanel-tabs" role="tablist" aria-label="Paneles del estudio" onKeyDown={onKeyDown}>
        {SIDE_TABS.map((t) => {
          const selected = t.id === tab;
          return (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[t.id] = el;
              }}
              id={`sidetab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`sidepanel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              className={`sidepanel-tab${selected ? " active" : ""}`}
              onClick={() => onTabChange(t.id)}
            >
              {t.label}
              {busy[t.id] && (
                <span className="sidepanel-busy" title="Proceso en curso">
                  <span className="sidepanel-busy-dot" aria-hidden="true" />
                  <span className="sr-only"> (en curso)</span>
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div {...panelProps("volumetria")}>
        <VolumetryPanel patient={study.patient} timepoint={study.timepoint} />
      </div>
      <div {...panelProps("segmentacion")}>
        <SegmentationPanel study={study} onCompleted={onSegmentationCompleted} onBusyChange={setSegBusy} />
      </div>
      <div {...panelProps("areas")}>
        <RiskSummary result={areas} focusedLabel={focusedLabel} onFocusLabel={onFocusLabel} />
        <AreasPanel
          study={study}
          onCompleted={onAreasCompleted}
          onLoaded={onAreasLoaded}
          onFocusLabel={onFocusLabel}
          focusedLabel={focusedLabel}
          onBusyChange={setAreasBusy}
        />
      </div>
      <div {...panelProps("longitudinal")}>
        <LongitudinalPanel patient={study.patient} timepoint={study.timepoint} />
      </div>
    </div>
  );
}
