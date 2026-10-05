"use client";

import { TooltipProvider } from "@nova/ui";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { Toaster, toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import { useLang } from "@/lib/i18n";
import { useUi } from "@/stores/ui";

function ThemeSync() {
  const theme = useUi((s) => s.theme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  return null;
}

function LangAttribute({ lang }: { lang: string }) {
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 15_000, retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2 },
        },
        queryCache: new QueryCache({}),
        mutationCache: new MutationCache({
          onError: (error) => {
            if (error instanceof ApiError && error.status !== 409) toast.error(error.message);
          },
        }),
      }),
  );
  const theme = useUi((s) => s.theme);
  const lang = useLang();
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ThemeSync />
        <LangAttribute lang={lang} />
        {/* Remount on language change so every label, date and number re-renders in the new language. */}
        <Fragment key={lang}>{children}</Fragment>
        <Toaster theme={theme} position="bottom-right" toastOptions={{ className: "!bg-surface !border-border !text-text" }} />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
