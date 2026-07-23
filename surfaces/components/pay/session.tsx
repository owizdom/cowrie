"use client";

/**
 * CowriePay session.
 *
 * Holds the signed-in user and keeps the balance current. The balance is
 * refreshed from the server after every terminal transfer rather than adjusted
 * locally: the sender's money is the one thing this app must never guess about,
 * and a refund that the client optimistically applied but the server rejected
 * would show a balance that does not exist.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken, setToken, type SessionUser } from "@/lib/api";

type SessionValue = {
  user: SessionUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signIn: (phone: string, pin: string) => Promise<void>;
  signOut: () => void;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const refresh = useCallback(async () => {
    if (!getToken("cowriepay")) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api<{ user: SessionUser }>("/auth/me", { audience: "cowriepay" });
      setUser(me.user);
    } catch {
      // An expired or invalid token is indistinguishable from no token as far
      // as the UI is concerned: both mean sign in again.
      clearToken("cowriepay");
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(
    async (phone: string, pin: string) => {
      const result = await api<{ token: string; user: SessionUser }>("/auth/login", {
        method: "POST",
        body: { phone, pin },
      });
      setToken("cowriepay", result.token);
      setUser(result.user);
    },
    [],
  );

  const signOut = useCallback(() => {
    clearToken("cowriepay");
    setUser(null);
    router.push("/pay/login");
  }, [router]);

  const value = useMemo(
    () => ({ user, loading, refresh, signIn, signOut }),
    [user, loading, refresh, signIn, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside SessionProvider");
  return context;
}

/** Redirect to the login screen when there is no session. */
export function useRequireSession() {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!session.loading && !session.user) router.replace("/pay/login");
  }, [session.loading, session.user, router]);

  return session;
}
