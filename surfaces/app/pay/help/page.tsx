"use client";
/** CowriePay — in-app help centre (SRS 2.6, "CowriePay: Help center in app"). */
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft } from "@/components/icons";
import { Card, Skeleton } from "@/components/ui";
import { TabBar } from "@/components/pay/tab-bar";
import { api } from "@/lib/api";

type Article = { slug: string; title: string; category: string; body: string };

export default function HelpPage() {
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try { setArticles((await api<{ articles: Article[] }>("/support/help")).articles); }
      catch { setArticles([]); }
    })();
  }, []);

  const categories = [...new Set((articles ?? []).map((a) => a.category))];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin pb-4">
        <header className="flex items-center gap-2 px-5 pb-2 pt-3">
          <Link href="/pay/support" className="flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-canvas" aria-label="Back"><ChevronLeft /></Link>
          <h1 className="text-[15px] font-semibold text-heading">Help centre</h1>
        </header>

        <div className="space-y-5 px-5 pt-2">
          {articles === null ? <Skeleton className="h-40 w-full rounded-card" /> : categories.map((category) => (
            <section key={category}>
              <h2 className="eyebrow mb-2">{category}</h2>
              <Card className="divide-y divide-line">
                {articles.filter((a) => a.category === category).map((article) => (
                  <div key={article.slug}>
                    <button type="button" onClick={() => setOpen(open === article.slug ? null : article.slug)} aria-expanded={open === article.slug} className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left">
                      <span className="text-[13px] font-semibold text-heading">{article.title}</span>
                      <span className="shrink-0 text-subtle" aria-hidden="true">{open === article.slug ? "−" : "+"}</span>
                    </button>
                    {open === article.slug ? <p className="px-4 pb-4 text-[13px] leading-relaxed text-muted">{article.body}</p> : null}
                  </div>
                ))}
              </Card>
            </section>
          ))}
        </div>
      </div>
      <TabBar />
    </div>
  );
}
