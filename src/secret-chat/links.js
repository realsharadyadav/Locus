// Guest links use a short, neutral path so a shared URL reads as a chat invite rather
// than as a page inside the Locus app. The original path stays supported for links that
// were sent out before the change.
export const GUEST_CHAT_PATH_RE = /^\/j\/([a-f0-9]+)/;
export const LEGACY_CHAT_PATH_RE = /^\/secret-chat\/([a-f0-9]+)/;

// Being remembered as a guest is sticky and survives restarts, so one path stays reserved
// for getting back to the app: /login forgets the remembered chat and hands this browser the
// sign-in gate instead. Without it a browser that once opened a share link could never reach
// the app again short of clearing site data.
export const HOST_ESCAPE_PATH_RE = /^\/login\/?$/;

export const guestChatPath = token => `/j/${token}`;

export const isHostEscapePath = pathname => HOST_ESCAPE_PATH_RE.test(pathname);

export function chatShareUrl(token) {
  return `${window.location.origin}${guestChatPath(token)}`;
}

export function matchChatPath(pathname) {
  const guest = pathname.match(GUEST_CHAT_PATH_RE);
  if (guest) return guest[1];
  const legacy = pathname.match(LEGACY_CHAT_PATH_RE);
  return legacy ? legacy[1] : null;
}
