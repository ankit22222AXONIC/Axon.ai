import { Landmark, GestureAction, GestureType } from './types';

function dist2D(a: Landmark, b: Landmark): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export class GestureClassifier {
  private prevPalmPos: { x: number; y: number } | null = null;
  private prevPinchDist: number | null = null;
  private lastActionTime: number = 0;

  public classify(handLandmarksList: Landmark[][]): GestureAction {
    if (!handLandmarksList || handLandmarksList.length === 0) {
      this.prevPalmPos = null;
      this.prevPinchDist = null;
      return {
        type: 'none',
        deltaX: 0,
        deltaY: 0,
        zoomDelta: 0,
        pinchDistance: 0,
        confidence: 0,
        handCount: 0,
        landmarks: []
      };
    }

    const hand = handLandmarksList[0];
    if (hand.length < 21) {
      return {
        type: 'none',
        deltaX: 0,
        deltaY: 0,
        zoomDelta: 0,
        pinchDistance: 0,
        confidence: 0,
        handCount: handLandmarksList.length,
        landmarks: handLandmarksList
      };
    }

    const wrist = hand[0];
    const thumbTip = hand[4];
    const indexMcp = hand[5];
    const indexTip = hand[8];
    const middleMcp = hand[9];
    const middleTip = hand[12];
    const ringMcp = hand[13];
    const ringTip = hand[16];
    const pinkyMcp = hand[17];
    const pinkyTip = hand[20];

    // Check finger extensions (distance from wrist compared to MCP joint)
    const indexExtended = dist2D(indexTip, wrist) > dist2D(indexMcp, wrist) * 1.25;
    const middleExtended = dist2D(middleTip, wrist) > dist2D(middleMcp, wrist) * 1.25;
    const ringExtended = dist2D(ringTip, wrist) > dist2D(ringMcp, wrist) * 1.25;
    const pinkyExtended = dist2D(pinkyTip, wrist) > dist2D(pinkyMcp, wrist) * 1.25;

    // Check fist: all 4 main fingers folded
    const isFist = !indexExtended && !middleExtended && !ringExtended && !pinkyExtended;

    // Check thumbs-up: thumb points up and other fingers are folded
    const isThumbsUp = isFist && thumbTip.y < hand[2].y - 0.08 && Math.abs(thumbTip.x - hand[2].x) < 0.12;

    // Pinch: thumb tip and index tip close together
    const pinchDistance = dist2D(thumbTip, indexTip);
    const isPinch = pinchDistance < 0.065;

    // Palm center estimation (mirroring X because webcams are mirrored for natural feel)
    const palmCenter = {
      x: 1 - ((wrist.x + indexMcp.x + pinkyMcp.x) / 3),
      y: (wrist.y + indexMcp.y + pinkyMcp.y) / 3
    };

    let detectedType: GestureType = 'none';
    let deltaX = 0;
    let deltaY = 0;
    let zoomDelta = 0;

    const now = Date.now();

    if (isThumbsUp) {
      detectedType = 'reset';
    } else if (isFist) {
      detectedType = 'fist_lock';
      // In fist lock, motion is intentionally stopped
      this.prevPalmPos = null;
      this.prevPinchDist = null;
    } else if (isPinch) {
      detectedType = 'pinch_zoom';
      if (this.prevPinchDist !== null) {
        // Change in pinch distance or vertical hand motion drives zoom
        const pinchDelta = pinchDistance - this.prevPinchDist;
        if (Math.abs(pinchDelta) > 0.003) {
          zoomDelta = pinchDelta * 18;
        }
      }
      this.prevPinchDist = pinchDistance;
      this.prevPalmPos = null;
    } else if (indexExtended && middleExtended) {
      // Open Palm / Panning mode
      detectedType = 'pan';
      if (this.prevPalmPos !== null) {
        const rawDx = palmCenter.x - this.prevPalmPos.x;
        const rawDy = palmCenter.y - this.prevPalmPos.y;

        // Apply sensitivity multiplier
        deltaX = rawDx * 1200;
        deltaY = rawDy * 1200;

        // Deadzone check: ignore tiny twitches
        if (Math.hypot(rawDx, rawDy) < 0.002) {
          deltaX = 0;
          deltaY = 0;
        }
      }
      this.prevPalmPos = palmCenter;
      this.prevPinchDist = null;
    } else {
      this.prevPalmPos = null;
      this.prevPinchDist = null;
    }

    this.lastActionTime = now;

    return {
      type: detectedType,
      deltaX,
      deltaY,
      zoomDelta,
      pinchDistance,
      confidence: 0.95,
      handCount: handLandmarksList.length,
      landmarks: handLandmarksList
    };
  }

  public reset(): void {
    this.prevPalmPos = null;
    this.prevPinchDist = null;
  }
}
