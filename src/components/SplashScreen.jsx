import React from 'react';
import { BRAND } from '../brand';
import { Logo } from './Logo';

/**
 * Boot screen shown while the first workspace load is in flight.
 *
 * `progress` is real: it tracks how many of the boot requests have settled,
 * so the bar never sits at a fake percentage waiting on a slow backend.
 * The whole screen fades in on a delay, so a fast local boot shows nothing
 * rather than a flash.
 */
export function SplashScreen({ progress = 0, status = 'Loading workspace' }) {
  return (
    <div className="splash" role="status" aria-live="polite">
      <div className="splash-inner">
        <Logo />
        <div
          className="splash-progress"
          role="progressbar"
          aria-valuenow={Math.round(progress)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Workspace loading progress"
        >
          <span className="splash-progress-fill" style={{ width: `${Math.max(4, Math.min(100, progress))}%` }} />
        </div>
        <p className="splash-status">{status}</p>
        <p className="splash-tagline">{BRAND.tagline}</p>
      </div>
    </div>
  );
}
