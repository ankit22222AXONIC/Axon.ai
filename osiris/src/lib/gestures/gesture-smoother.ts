export class GestureSmoother {
  private smoothDx: number = 0;
  private smoothDy: number = 0;
  private smoothZoom: number = 0;
  private readonly alpha: number;

  constructor(alpha: number = 0.28) {
    this.alpha = alpha;
  }

  public smooth(dx: number, dy: number, zoomDelta: number) {
    this.smoothDx = this.smoothDx * (1 - this.alpha) + dx * this.alpha;
    this.smoothDy = this.smoothDy * (1 - this.alpha) + dy * this.alpha;
    this.smoothZoom = this.smoothZoom * (1 - this.alpha) + zoomDelta * this.alpha;

    // Zero out tiny residual momentum
    if (Math.abs(this.smoothDx) < 0.2) this.smoothDx = 0;
    if (Math.abs(this.smoothDy) < 0.2) this.smoothDy = 0;
    if (Math.abs(this.smoothZoom) < 0.005) this.smoothZoom = 0;

    return {
      dx: this.smoothDx,
      dy: this.smoothDy,
      zoomDelta: this.smoothZoom
    };
  }

  public reset() {
    this.smoothDx = 0;
    this.smoothDy = 0;
    this.smoothZoom = 0;
  }
}
