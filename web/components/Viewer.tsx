"use client";

import { useEffect, useRef } from "react";
import OpenSeadragon from "openseadragon";

export type Region = {
  id: string;
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
  confidence: number;
};

type Props = {
  imageUrl: string | null;
  regions: Region[];
  activeId: string | null;
  showBoxes: boolean;
  onSelect: (id: string) => void;
};

export default function Viewer({ imageUrl, regions, activeId, showBoxes, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<ReturnType<typeof OpenSeadragon> | null>(null);
  const buttons = useRef<Record<string, HTMLButtonElement | null>>({});
  const placeRef = useRef<() => void>(() => {});
  const regionsRef = useRef(regions);
  regionsRef.current = regions;
  const activeRef = useRef(activeId);
  activeRef.current = activeId;

  useEffect(() => {
    if (!host.current || !imageUrl) return;
    const viewer = OpenSeadragon({
      element: host.current,
      tileSources: { type: "image", url: imageUrl },
      showNavigationControl: false,
      // Canvas is reliable for a single page image. WebGL draws a black frame
      // when the browser has no working GPU.
      drawer: ["canvas", "html"],
      gestureSettingsMouse: { clickToZoom: false },
      animationTime: 0.25,
      visibilityRatio: 0.4,
      constrainDuringPan: true,
    });
    viewerRef.current = viewer;

    const place = () => {
      const item = viewer.world.getItemAt(0);
      if (!item) return;
      for (const region of regionsRef.current) {
        const button = buttons.current[region.id];
        if (!button) continue;
        const topLeft = viewer.viewport.viewportToViewerElementCoordinates(
          viewer.viewport.imageToViewportCoordinates(region.x, region.y),
        );
        const bottomRight = viewer.viewport.viewportToViewerElementCoordinates(
          viewer.viewport.imageToViewportCoordinates(region.x + region.w, region.y + region.h),
        );
        button.style.left = `${topLeft.x}px`;
        button.style.top = `${topLeft.y}px`;
        button.style.width = `${Math.max(4, bottomRight.x - topLeft.x)}px`;
        button.style.height = `${Math.max(4, bottomRight.y - topLeft.y)}px`;
      }
    };
    const jump = () => {
      const id = activeRef.current;
      const region = regionsRef.current.find((item) => item.id === id);
      const image = viewer.world.getItemAt(0);
      if (!region || !image) return;
      const padX = Math.max(8, region.w * 0.35);
      const padY = Math.max(8, region.h * 1.5);
      const rect = image.imageToViewportRectangle(
        region.x - padX,
        region.y - padY,
        region.w + padX * 2,
        region.h + padY * 2,
      );
      viewer.viewport.fitBounds(rect, false);
    };
    viewer.addHandler("open", () => { place(); jump(); });
    viewer.addHandler("update-viewport", place);
    placeRef.current = place;
    return () => {
      placeRef.current = () => {};
      viewer.destroy();
      viewerRef.current = null;
    };
  }, [imageUrl]);

  useEffect(() => {
    placeRef.current();
  }, [regions, showBoxes]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const region = regionsRef.current.find((item) => item.id === activeId);
    const image = viewer?.world.getItemAt(0);
    if (!viewer || !region || !image || !activeId) return;
    const padX = Math.max(8, region.w * 0.35);
    const padY = Math.max(8, region.h * 1.5);
    viewer.viewport.fitBounds(
      image.imageToViewportRectangle(region.x - padX, region.y - padY, region.w + padX * 2, region.h + padY * 2),
      false,
    );
  }, [activeId]);

  function zoom(factor: number) {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.viewport.zoomBy(factor);
    viewer.viewport.applyConstraints();
  }

  return (
    <div>
      <div className="toolbar">
        <button type="button" className="ghost" onClick={() => zoom(1.25)}>Zoom in</button>
        <button type="button" className="ghost" onClick={() => zoom(0.8)}>Zoom out</button>
        <button type="button" className="ghost" onClick={() => viewerRef.current?.viewport.goHome(true)}>Fit page</button>
      </div>
      <div className="viewer-frame">
        {imageUrl ? <div ref={host} className="osd" /> : <p className="quiet" style={{ color: "#f3efe6", padding: 16 }}>No page image yet.</p>}
        {showBoxes && imageUrl && (
          <div className="overlay">
            {regions.map((region) => (
              <button
                key={region.id}
                type="button"
                ref={(node) => { buttons.current[region.id] = node; }}
                className={`region-box${region.id === activeId ? " active" : ""}${region.confidence > 0 && region.confidence < 0.6 ? " low" : ""}`}
                onClick={() => onSelect(region.id)}
              >
                <span className="sr">{region.text || "Empty region"}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
