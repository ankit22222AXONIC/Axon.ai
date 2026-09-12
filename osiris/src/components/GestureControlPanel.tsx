'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Hand, Video, VideoOff, Eye, EyeOff, X, Zap, Lock, ZoomIn, Compass } from 'lucide-react';
import { HandDetectorService } from '@/lib/gestures/hand-detector';
import { GestureClassifier } from '@/lib/gestures/gesture-classifier';
import { GestureSmoother } from '@/lib/gestures/gesture-smoother';
import { GestureAction, Landmark } from '@/lib/gestures/types';

interface GestureControlPanelProps {
  onGesture: (action: { type: string; dx: number; dy: number; zoomDelta: number }) => void;
  isOpen: boolean;
  onClose: () => void;
}

const CONNECTIONS = [
  // Thumb
  [0, 1], [1, 2], [2, 3], [3, 4],
  // Index
  [0, 5], [5, 6], [6, 7], [7, 8],
  // Middle
  [5, 9], [9, 10], [10, 11], [11, 12],
  // Ring
  [9, 13], [13, 14], [14, 15], [15, 16],
  // Pinky
  [13, 17], [17, 18], [18, 19], [19, 20],
  // Base of palm
  [0, 17]
];

export default function GestureControlPanel({ onGesture, isOpen, onClose }: GestureControlPanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const detectorRef = useRef<HandDetectorService | null>(null);
  const classifierRef = useRef<GestureClassifier>(new GestureClassifier());
  const smootherRef = useRef<GestureSmoother>(new GestureSmoother(0.35));

  const [loading, setLoading] = useState(true);
  const [activeGesture, setActiveGesture] = useState<string>('none');
  const [minimized, setMinimized] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const requestRef = useRef<number | null>(null);

  const processFrame = useCallback(() => {
    if (!videoRef.current || !canvasRef.current || !detectorRef.current) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');

    if (video.readyState >= 2 && ctx) {
      canvas.width = video.videoWidth || 320;
      canvas.height = video.videoHeight || 240;

      // Detect hands
      const landmarksList = detectorRef.current.detect(video, performance.now());

      // Clear canvas
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (landmarksList && landmarksList.length > 0) {
        const hand = landmarksList[0];

        // Draw futuristic holographic hand skeleton
        ctx.save();
        // Mirror the canvas rendering horizontally to match user's mirror view
        ctx.translate(canvas.width, 0);
        ctx.scale(-1, 1);

        // Draw bone connections
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = 'rgba(0, 255, 200, 0.75)';
        ctx.shadowColor = '#00ffcc';
        ctx.shadowBlur = 8;

        for (const [startIdx, endIdx] of CONNECTIONS) {
          const start = hand[startIdx];
          const end = hand[endIdx];
          ctx.beginPath();
          ctx.moveTo(start.x * canvas.width, start.y * canvas.height);
          ctx.lineTo(end.x * canvas.width, end.y * canvas.height);
          ctx.stroke();
        }

        // Draw joint nodes
        for (let i = 0; i < hand.length; i++) {
          const p = hand[i];
          const px = p.x * canvas.width;
          const py = p.y * canvas.height;

          ctx.beginPath();
          ctx.arc(px, py, i === 4 || i === 8 ? 4.5 : 2.5, 0, Math.PI * 2);
          ctx.fillStyle = i === 4 || i === 8 ? '#f59e0b' : '#ffffff';
          ctx.shadowColor = i === 4 || i === 8 ? '#f59e0b' : '#00ffcc';
          ctx.shadowBlur = 6;
          ctx.fill();
        }

        ctx.restore();

        // Classify gesture
        const action = classifierRef.current.classify(landmarksList);
        setActiveGesture(action.type);

        // Apply exponential smoothing to prevent camera twitches
        const smoothed = smootherRef.current.smooth(action.deltaX, action.deltaY, action.zoomDelta);

        // Forward to map
        onGesture({
          type: action.type,
          dx: smoothed.dx,
          dy: smoothed.dy,
          zoomDelta: smoothed.zoomDelta
        });
      } else {
        classifierRef.current.reset();
        smootherRef.current.reset();
        setActiveGesture('searching');
        onGesture({ type: 'none', dx: 0, dy: 0, zoomDelta: 0 });
      }
    }

    requestRef.current = requestAnimationFrame(processFrame);
  }, [onGesture]);

  useEffect(() => {
    if (!isOpen) {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      if (videoRef.current && videoRef.current.srcObject) {
        const stream = videoRef.current.srcObject as MediaStream;
        stream.getTracks().forEach(t => t.stop());
        videoRef.current.srcObject = null;
      }
      return;
    }

    let stream: MediaStream | null = null;
    let isCancelled = false;

    async function startGestureEngine() {
      try {
        setLoading(true);
        setCameraError(null);

        // Initialize MediaPipe detector
        if (!detectorRef.current) {
          detectorRef.current = new HandDetectorService();
          await detectorRef.current.initialize();
        }

        // Request webcam
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 480 },
            height: { ideal: 360 },
            facingMode: 'user'
          },
          audio: false
        });

        if (isCancelled) {
          stream.getTracks().forEach(t => t.stop());
          return;
        }

        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }

        setLoading(false);
        requestRef.current = requestAnimationFrame(processFrame);
      } catch (err: any) {
        console.error('Camera access or model load error:', err);
        setCameraError(err.message || 'Camera permission denied');
        setLoading(false);
      }
    }

    startGestureEngine();

    return () => {
      isCancelled = true;
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      if (stream) {
        stream.getTracks().forEach(t => t.stop());
      }
    };
  }, [isOpen, processFrame]);

  if (!isOpen) return null;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.9, y: 20 }}
      className="fixed bottom-24 right-4 md:bottom-16 md:right-20 z-[250] pointer-events-auto"
    >
      <div className="w-64 sm:w-72 rounded-2xl bg-[#121314]/90 border border-[#2d2f31] backdrop-blur-xl shadow-2xl overflow-hidden flex flex-col font-sans">
        
        {/* Header bar */}
        <div className="px-3.5 py-2.5 bg-[#18191a]/95 border-b border-[#2d2f31] flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span className="text-xs font-semibold tracking-wide text-neutral-200 uppercase font-mono">
              Air Gestures HUD
            </span>
          </div>

          <div className="flex items-center space-x-1">
            <button
              onClick={() => setMinimized(!minimized)}
              className="p-1 rounded text-neutral-400 hover:text-neutral-200 hover:bg-[#282a2c] transition-colors"
              title={minimized ? "Expand video" : "Minimize video"}
            >
              {minimized ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
            </button>
            <button
              onClick={onClose}
              className="p-1 rounded text-neutral-400 hover:text-rose-400 hover:bg-[#282a2c] transition-colors"
              title="Turn off air gestures"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Video / HUD Canvas Viewport */}
        {!minimized && (
          <div className="relative w-full aspect-[4/3] bg-black/80 overflow-hidden flex items-center justify-center">
            {loading && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70 text-xs text-neutral-400 space-y-2 z-10">
                <div className="w-5 h-5 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin"></div>
                <span className="font-mono text-[11px]">Loading Vision AI...</span>
              </div>
            )}

            {cameraError && (
              <div className="p-4 text-center text-xs text-rose-400 space-y-1 z-10">
                <p className="font-semibold">Webcam Offline</p>
                <p className="text-[10px] text-neutral-400">{cameraError}</p>
              </div>
            )}

            {/* Hidden source video */}
            <video
              ref={videoRef}
              playsInline
              muted
              className="absolute inset-0 w-full h-full object-cover opacity-35 scale-x-[-1]"
            />

            {/* Futuristic HUD Canvas */}
            <canvas
              ref={canvasRef}
              className="absolute inset-0 w-full h-full object-cover z-0"
            />

            {/* Sci-Fi Targeting Crosshair Graphics */}
            <div className="absolute inset-2 border border-emerald-500/15 pointer-events-none rounded-lg flex items-center justify-center">
              <div className="w-3 h-3 border border-emerald-500/40 rounded-full"></div>
            </div>
          </div>
        )}

        {/* Gesture Status Pill Footer */}
        <div className="px-3.5 py-2.5 bg-[#151617] border-t border-[#2d2f31] flex items-center justify-between text-xs">
          <div className="flex items-center space-x-2">
            {activeGesture === 'pan' && (
              <span className="flex items-center space-x-1.5 text-emerald-400 font-mono font-medium">
                <Hand className="w-3.5 h-3.5" />
                <span>[PANNING]</span>
              </span>
            )}
            {activeGesture === 'pinch_zoom' && (
              <span className="flex items-center space-x-1.5 text-amber-400 font-mono font-medium">
                <ZoomIn className="w-3.5 h-3.5" />
                <span>[PINCH ZOOM]</span>
              </span>
            )}
            {activeGesture === 'fist_lock' && (
              <span className="flex items-center space-x-1.5 text-rose-400 font-mono font-medium">
                <Lock className="w-3.5 h-3.5" />
                <span>[LOCKED]</span>
              </span>
            )}
            {activeGesture === 'reset' && (
              <span className="flex items-center space-x-1.5 text-indigo-400 font-mono font-medium">
                <Compass className="w-3.5 h-3.5" />
                <span>[ORBIT RESET]</span>
              </span>
            )}
            {(activeGesture === 'searching' || activeGesture === 'none') && (
              <span className="text-neutral-500 font-mono text-[11px]">
                Show hand to camera...
              </span>
            )}
          </div>

          <span className="text-[10px] text-neutral-500 font-mono uppercase">
            GPU Vision
          </span>
        </div>

      </div>
    </motion.div>
  );
}
