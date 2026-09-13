import { NextResponse } from 'next/server';

export async function GET() {
  return NextResponse.json({
    status: 'operational',
    platform: 'OSIRIS',
    version: '1.0.0',
    uptime: process.uptime ? Math.round(process.uptime()) : 0,
    timestamp: new Date().toISOString(),
    endpoints: [
      '/api/live-news',
      '/api/conflicts',
      '/api/frontlines',
      '/api/country-risk',
      '/api/earthquakes',
      '/api/fires',
      '/api/weather',
      '/api/space-weather',
      '/api/satellites',
      '/api/flights',
      '/api/aircraft',
      '/api/maritime',
      '/api/malware',
      '/api/cyber-attacks',
      '/api/cctv',
      '/api/gdelt-events',
      '/api/region-dossier',
      '/api/markets',
      '/api/news',
    ],
  });
}
