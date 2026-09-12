import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';
import { Landmark } from './types';

export class HandDetectorService {
  private landmarker: HandLandmarker | null = null;
  private isInitializing: boolean = false;

  public async initialize(): Promise<void> {
    if (this.landmarker || this.isInitializing) return;
    this.isInitializing = true;

    try {
      const vision = await FilesetResolver.forVisionTasks(
        'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
      );

      this.landmarker = await HandLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath:
            'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
          delegate: 'GPU'
        },
        runningMode: 'VIDEO',
        numHands: 1,
        minHandDetectionConfidence: 0.6,
        minHandPresenceConfidence: 0.6,
        minTrackingConfidence: 0.6
      });
    } catch (err) {
      console.warn('GPU delegate failed for HandLandmarker, falling back to CPU:', err);
      try {
        const vision = await FilesetResolver.forVisionTasks(
          'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
        );
        this.landmarker = await HandLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath:
              'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
            delegate: 'CPU'
          },
          runningMode: 'VIDEO',
          numHands: 1
        });
      } catch (fallbackErr) {
        console.error('Failed to initialize HandLandmarker:', fallbackErr);
        throw fallbackErr;
      }
    } finally {
      this.isInitializing = false;
    }
  }

  public detect(video: HTMLVideoElement, timestamp: number): Landmark[][] | null {
    if (!this.landmarker || video.readyState < 2) return null;
    try {
      const result = this.landmarker.detectForVideo(video, timestamp);
      return (result.landmarks as Landmark[][]) || null;
    } catch (e) {
      return null;
    }
  }

  public dispose(): void {
    if (this.landmarker) {
      this.landmarker.close();
      this.landmarker = null;
    }
  }
}
