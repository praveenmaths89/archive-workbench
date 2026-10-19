declare module "openseadragon" {
  interface Viewer {
    world: { getItemAt(index: number): ImageItem | null };
    viewport: {
      zoomBy(factor: number): void;
      applyConstraints(immediately?: boolean): void;
      goHome(immediately?: boolean): void;
      fitBounds(rect: Rect, immediately?: boolean): void;
      imageToViewportCoordinates(x: number, y: number): Point;
      viewportToViewerElementCoordinates(point: Point): Point;
    };
    addHandler(event: string, handler: (event?: unknown) => void): void;
    destroy(): void;
  }
  interface ImageItem {
    imageToViewportRectangle(x: number, y: number, w: number, h: number): Rect;
  }
  interface Point {
    x: number;
    y: number;
  }
  interface Rect {
    x: number;
    y: number;
    width: number;
    height: number;
  }
  interface Options {
    element: HTMLElement;
    tileSources: { type: string; url: string };
    showNavigationControl?: boolean;
    drawer?: string | string[];
    gestureSettingsMouse?: { clickToZoom?: boolean };
    animationTime?: number;
    visibilityRatio?: number;
    constrainDuringPan?: boolean;
    crossOriginPolicy?: string;
  }
  interface OSD {
    (options: Options): Viewer;
  }
  const OpenSeadragon: OSD;
  export default OpenSeadragon;
}
