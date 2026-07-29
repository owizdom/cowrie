"use client";

/**
 * The shuffled PIN keypad, shared by the login and send-confirmation screens.
 *
 * SRS 3.1 specifies "six-digit PIN with a randomized keypad". The keys move on
 * every render so that nobody watching can learn a PIN from the shape a thumb
 * makes, and so a smudge on the glass says nothing about the digits.
 *
 * Both screens previously kept their own copy of this, and both carried the
 * same two defects that came from starting the digits empty. It lives in one
 * place now so it is fixed in one place.
 */

import { useCallback, useEffect, useLayoutEffect, useState } from "react";

/** Fisher-Yates. Unbiased, unlike sort(() => Math.random() - 0.5). */
export function shuffled(): number[] {
  const digits = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
  for (let i = digits.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [digits[i], digits[j]] = [digits[j], digits[i]];
  }
  return digits;
}

/** The order rendered on the server and on the first client render. */
const ORDERED = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];

/**
 * `useLayoutEffect` runs before the browser paints; `useEffect` runs after. The
 * difference is the whole point here, so the server - which has no layout
 * phase and would warn - gets the plain effect instead.
 */
const useBeforePaint = typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * Returns the keypad digits and a way to re-shuffle them.
 *
 * Seeded with 0-9 in order rather than an empty array, which is what fixes two
 * things at once:
 *
 *   * The pad no longer paints with no digits on it. The shuffle cannot happen
 *     during render - the server and the client would produce different markup
 *     and hydration would fail - so it happens in a layout effect, which lands
 *     before the first paint. An ordered seed keeps the server and client
 *     markup identical until then.
 *
 *   * `keys[9]` is never undefined. The tenth key is rendered separately, and
 *     with an empty seed it was a live button carrying `undefined`; pressing it
 *     appended the nine characters of "undefined" to the PIN, which filled all
 *     six dots, never reached the six-character submit check, and left the
 *     screen looking complete while doing nothing.
 */
export function useShuffledKeys(): { keys: number[]; reshuffle: () => void } {
  const [keys, setKeys] = useState<number[]>(ORDERED);

  useBeforePaint(() => setKeys(shuffled()), []);

  const reshuffle = useCallback(() => setKeys(shuffled()), []);

  return { keys, reshuffle };
}
