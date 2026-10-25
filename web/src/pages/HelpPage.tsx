import { useEffect, useMemo, useState } from "react";
import { HelpCircle } from "lucide-react";
import { H2 } from "@/components/ui/h2";
import { Card, CardContent } from "@/components/ui/Card";
import { Markdown } from "@/components/Markdown";
import { usePageHeader } from "@/contexts/usePageHeader";
import { HELP_SECTIONS } from "@/content/help";
import { useLocation } from "react-router";

export default function HelpPage() {
  const [active, setActive] = useState(HELP_SECTIONS[0].id);
  const { setEnd } = usePageHeader();
  const { hash } = useLocation();

  useEffect(() => {
    setEnd(null);
  }, [setEnd]);

  // Deep links: /help#wakes (the login page links to #authentication).
  useEffect(() => {
    const id = hash.replace("#", "");
    if (id && HELP_SECTIONS.some((s) => s.id === id)) setActive(id);
  }, [hash]);

  const section = useMemo(
    () => HELP_SECTIONS.find((s) => s.id === active) ?? HELP_SECTIONS[0],
    [active],
  );

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center gap-2">
        <HelpCircle className="h-5 w-5" />
        <H2>Help</H2>
      </div>

      <div className="flex flex-wrap gap-2">
        {HELP_SECTIONS.map((s) => (
          <button
            key={s.id}
            id={s.id}
            className={`rounded-control border px-3 py-1.5 text-sm ${active === s.id ? "border-primary bg-primary/10 text-primary" : "border-border"}`}
            onClick={() => setActive(s.id)}
          >
            {s.title}
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="py-4">
          <H2 className="text-base">{section.title}</H2>
          <div className="pt-2 text-sm">
            <Markdown content={section.body} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
