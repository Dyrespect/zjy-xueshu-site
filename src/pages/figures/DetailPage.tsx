import { useEffect, useState } from "react";
import { useLocation, useParams } from "react-router";

import { FeedbackDialog } from "@/blocks/feedback-dialog";
import { sendFeedback } from "@/blocks/feedback-dialog/load";
import { FigureDetailView } from "@/blocks/figure-detail";
import { loadDetail, loadSimilar } from "@/blocks/figure-detail/load";
import { SubmitDialog } from "@/blocks/submit-dialog";
import { sendSubmission } from "@/blocks/submit-dialog/load";
import type { FigureCard, FigureDetail, SearchContext } from "@/lib/figures-types";

import { figureHref, searchHref, typeHref, useGallery, useTitle } from "./gallery-context";

export default function DetailPage() {
  const { id = "" } = useParams();
  const fid = Number(id);
  const location = useLocation();
  const from = (location.state as SearchContext | null) ?? null;
  const { openAllLibrary } = useGallery();
  const [detail, setDetail] = useState<FigureDetail | null>(null);
  const [similar, setSimilar] = useState<FigureCard[] | null>(null);
  const [error, setError] = useState("");
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);
  useTitle(detail?.title);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setSimilar(null);
    setError("");
    if (!Number.isInteger(fid)) {
      setError("没有这张图");
      return;
    }
    loadDetail(fid).then(
      (d) => alive && setDetail(d),
      (e: Error) => alive && setError(e.message),
    );
    loadSimilar(fid).then(
      (s) => alive && setSimilar(s),
      () => alive && setSimilar([]),
    );
    return () => {
      alive = false;
    };
  }, [fid]);

  return (
    <main className="mx-auto max-w-6xl px-4 pt-6 pb-16 sm:px-6 sm:pt-8">
      <FigureDetailView
        detail={detail}
        loading={!detail && !error}
        error={error}
        similar={similar}
        searchHref={(w) => searchHref(w)}
        typeHref={typeHref}
        cardHref={(c) => figureHref(c.id)}
        cardState={from}
        onFeedback={() => setFeedbackOpen(true)}
        onSubmitFigure={() => setSubmitOpen(true)}
        onAllLibrary={openAllLibrary}
      />
      <FeedbackDialog
        open={feedbackOpen}
        onOpenChange={setFeedbackOpen}
        query={from?.query}
        onSubmit={(b) => sendFeedback(fid, { ...b, query: from?.query ?? "", search_id: from?.searchId ?? null })}
      />
      <SubmitDialog open={submitOpen} onOpenChange={setSubmitOpen} onSubmit={sendSubmission} />
    </main>
  );
}
