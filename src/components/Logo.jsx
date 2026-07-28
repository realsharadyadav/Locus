import React from 'react';
import { BRAND } from '../brand';

export function Logo() {
  return (
    <div className="logo">
      <svg className="logo-mark" viewBox="0 0 25 25" width="34" height="34" aria-hidden="true">
        <circle className="logo-ping" cx="12.5" cy="12.5" r="9" fill="none" strokeWidth="1.4" />
        <circle className="logo-ring-outer" cx="12.5" cy="12.5" r="10" fill="none" strokeWidth="2" />
        <circle className="logo-ring-inner" cx="12.5" cy="12.5" r="5.6" fill="none" strokeWidth="2" />
        <circle className="logo-dot" cx="12.5" cy="12.5" r="2.4" />
      </svg>
      <span>{BRAND.name}</span>
    </div>
  );
}
