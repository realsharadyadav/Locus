import { useEffect, useState } from 'react';
import { secretChatApi } from './api';
import { clientId as readClientId, peekHostKey } from './identity';

// Short enough that the badge clears within a few seconds of you reading a room elsewhere
// in the app; the request is one small query against your own rooms.
const POLL_INTERVAL_MS = 6000;

/**
 * Total unread private-chat messages across all of this browser's rooms, for the badge on
 * the Private nav item. Uses `peekHostKey` so a browser that has never created a room does
 * not get one minted just by rendering the sidebar.
 */
export function useSecretChatUnread(enabled = true) {
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;

    const check = () => {
      const hostKey = peekHostKey();
      if (!hostKey) {
        setUnread(0);
        return;
      }
      secretChatApi.rooms(hostKey, readClientId())
        .then(rooms => {
          if (cancelled) return;
          setUnread(rooms.reduce((total, room) => total + room.unread_count, 0));
        })
        .catch(() => {
          // Connectivity problems are already surfaced by the app's offline banner.
        });
    };

    check();
    const timer = setInterval(check, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  return unread;
}
