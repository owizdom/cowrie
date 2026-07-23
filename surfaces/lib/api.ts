/**
 * Client for the Cowrie orchestration tier.
 *
 * Requests go to /api/*, which next.config.ts rewrites to the Python service.
 * That keeps the browser on one origin: no CORS preflight, and the PWA service
 * worker only ever sees same-origin requests.
 *
 * Sessions are held in localStorage rather than a cookie, because the three
 * audiences (CowriePay, admin, regulator) are separate tokens that must not be
 * sent to each other's endpoints - a cookie would be attached to all of them.
 */

export const API_BASE = "/api";

export type Audience = "cowriepay" | "admin" | "regulator";

const TOKEN_KEYS: Record<Audience, string> = {
  cowriepay: "cowrie.session.pay",
  admin: "cowrie.session.admin",
  regulator: "cowrie.session.regulator",
};

export function getToken(audience: Audience): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEYS[audience]);
}

export function setToken(audience: Audience, token: string): void {
  window.localStorage.setItem(TOKEN_KEYS[audience], token);
}

export function clearToken(audience: Audience): void {
  window.localStorage.removeItem(TOKEN_KEYS[audience]);
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  audience?: Audience;
  apiKey?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, audience, apiKey, headers = {}, signal } = options;

  const requestHeaders: Record<string, string> = { ...headers };
  if (body !== undefined) requestHeaders["Content-Type"] = "application/json";

  if (audience) {
    const token = getToken(audience);
    if (token) requestHeaders["Authorization"] = `Bearer ${token}`;
  }
  if (apiKey) requestHeaders["X-API-Key"] = apiKey;

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: requestHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!response.ok) {
    // FastAPI puts the message in `detail`; validation errors put a list there.
    // Both are unwrapped here so callers can show `error.message` directly
    // rather than each one re-deriving a readable string.
    const detail = (parsed as { detail?: unknown } | null)?.detail;
    let message = `Request failed (${response.status})`;
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string; loc?: string[] };
      const field = first.loc?.slice(1).join(".");
      message = field ? `${field}: ${first.msg}` : (first.msg ?? message);
    } else if ((parsed as { error?: { message?: string } } | null)?.error?.message) {
      message = (parsed as { error: { message: string } }).error.message;
    }
    throw new ApiError(response.status, message, parsed);
  }

  return parsed as T;
}

/** Open the transaction status WebSocket (SRS 3.4). */
export function openSocket(
  channel: "transfers" | "admin" | "public",
  onEvent: (event: SocketEvent) => void,
): () => void {
  if (typeof window === "undefined") return () => {};

  const audience: Audience = channel === "admin" ? "admin" : "cowriepay";
  const token = channel === "public" ? "" : (getToken(audience) ?? "");

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${window.location.host}/api/ws/${channel}${token ? `?token=${encodeURIComponent(token)}` : ""}`;

  let socket: WebSocket | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let attempts = 0;

  const connect = () => {
    if (closed) return;
    socket = new WebSocket(url);

    socket.onmessage = (message) => {
      try {
        const payload = JSON.parse(message.data) as SocketEvent;
        if (payload.event === "heartbeat") return;
        onEvent(payload);
      } catch {
        /* a malformed frame must not take the socket down */
      }
    };

    socket.onopen = () => {
      attempts = 0;
    };

    socket.onclose = () => {
      if (closed) return;
      // Back off, but keep trying: a transfer takes ~30 seconds and a dropped
      // socket mid-settlement should recover on its own rather than leaving the
      // status screen frozen. The server replays recent events on reconnect.
      attempts += 1;
      const delay = Math.min(1000 * 2 ** (attempts - 1), 15000);
      retry = setTimeout(connect, delay);
    };
  };

  connect();

  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    socket?.close();
  };
}

export type SocketEvent = {
  channel: string;
  event: string;
  ts: string;
  data: Record<string, unknown>;
};

// ---------------------------------------------------------------------------
// shared response shapes
// ---------------------------------------------------------------------------

export type Money = { amount: string; currency: string };

/** The four itemised charges of NFR 6. Never collapsed into one number. */
export type Fees = {
  fxSpread: string;
  networkGas: string;
  liquiditySpread: string;
  cowrieFee: string;
  total: string;
  currency: string;
};

export type Quote = {
  id: string;
  corridor: string;
  source: Money;
  destination: Money;
  fees: Fees;
  fxRate: string;
  midMarketRate: string;
  usdEquivalent: string;
  expiresAt: string;
  secondsRemaining: number;
  costRatio: string;
  costPercent: string;
  lockSeconds: number;
  requiresSecondFactor: boolean;
  limitUsd: number;
  withinLimit: boolean;
};

export type OnchainRecord = {
  txHash: string;
  blockNumber: number;
  confirmations: number;
  requiredConfirmations: number;
  contractAddress: string;
  isFinal: boolean;
  rolledBack: boolean;
  chainMode: string;
  cngnAmount: string;
  cusdcAmount: string;
};

export type TransferState =
  | "CREATED"
  | "QUOTED"
  | "AUTHORIZED"
  | "ONRAMP_PENDING"
  | "BRIDGING"
  | "OFFRAMP_PENDING"
  | "SETTLED"
  | "REFUNDING"
  | "REFUNDED"
  | "FAILED"
  | "CANCELLED";

export type Transfer = {
  id: string;
  reference: string;
  state: TransferState;
  createdAt: string;
  settledAt: string | null;
  source: Money;
  destination: Money;
  fees: Fees;
  fxRate: string;
  recipient: { name: string; msisdn: string };
  channel: string;
  monoReference: string;
  mpesaReceipt: string;
  failureReason: string;
  riskLevel: "LOW" | "MEDIUM" | "HIGH";
  riskFlags: string[];
  isStuck: boolean;
  canCancel: boolean;
  secondsInState: number;
  costPercent: string;
  onchain: OnchainRecord | null;
  stepUp?: { required: boolean; challengeId?: string; reason?: string; code?: string };
  quoteExpiresAt?: string;
  secondsRemaining?: number;
};

export type SessionUser = {
  id: string;
  fullName: string;
  phone: string;
  email: string;
  country: string;
  kycLevel: "NONE" | "TIER1" | "TIER2" | "TIER3";
  limitUsd: number;
  ngnBalance: string;
  bankName: string;
  bankAccountMasked: string;
  isFrozen: boolean;
};
