export type GestureType = 'none' | 'pan' | 'pinch_zoom' | 'fist_lock' | 'reset';

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export interface GestureAction {
  type: GestureType;
  // Normalized 2D panning velocity (-1 to 1)
  deltaX: number;
  deltaY: number;
  // Zoom change rate (-1 zoom out, +1 zoom in)
  zoomDelta: number;
  // Distance between pinch fingers (thumb & index)
  pinchDistance: number;
  // Confidence score
  confidence: number;
  // Detected hand count
  handCount: number;
  // Raw landmarks for HUD wireframe rendering
  landmarks: Landmark[][];
}
