import { useEffect, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import {
  Field,
  FieldSet,
  FieldLegend,
  FieldGroup,
  FieldLabel,
} from "../components/ui/field";
import { Alert, AlertDescription } from "../components/ui/alert";
import { useTranslation } from "../i18n";
import { readDailyTrackList } from "./queries";
import type { DailyTrackListItem } from "./DailyTracksPage";
import type { ChooseTracks } from "./trackingQuota";
export function useTrackingSelection() {
  const { t } = useTranslation("billing");
  const [choice, setChoice] = useState<{
    limit: number;
    targetId?: string;
  } | null>(null);
  const [items, setItems] = useState<DailyTrackListItem[] | null>(null);
  const [selection, setSelection] = useState<string[]>([]);
  const [failed, setFailed] = useState(false);
  const [restricted, setRestricted] = useState<string[] | null>(null);
  const resolve = useRef<((value: string[] | null) => void) | null>(null);
  const choose: ChooseTracks = (limit, targetId) =>
    new Promise((done) => {
      resolve.current = done;
      setItems(null);
      setSelection(targetId ? [targetId] : []);
      setFailed(false);
      setChoice({ limit, targetId });
    });
  function close(value: string[] | null) {
    resolve.current?.(value);
    resolve.current = null;
    setChoice(null);
    setRestricted(null);
  }
  useEffect(
    () => () => {
      resolve.current?.(null);
      resolve.current = null;
    },
    [],
  );
  useEffect(() => {
    if (!choice && !restricted) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const all: DailyTrackListItem[] = [];
        let cursor: string | undefined;
        do {
          const page = await readDailyTrackList(controller.signal, cursor);
          all.push(...page.items);
          cursor = page.next_cursor ?? undefined;
        } while (cursor);
        if (!controller.signal.aborted)
          setItems(all.filter((item) => item.status !== "stopped"));
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    })();
    return () => controller.abort();
  }, [choice, restricted]);
  const dialog = (
    <Dialog
      open={choice !== null || restricted !== null}
      onOpenChange={(open) => {
        if (!open) close(null);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t(restricted ? "selectedTracks" : "selectionTitle")}
          </DialogTitle>
          <DialogDescription>
            {restricted
              ? t("notSelected")
              : t("selectionDescription", { limit: choice?.limit })}
          </DialogDescription>
        </DialogHeader>
        {failed ? (
          <Alert variant="destructive">
            <AlertDescription>{t("selectionLoadError")}</AlertDescription>
          </Alert>
        ) : null}
        {restricted ? (
          <ul className="flex flex-col gap-2">
            {restricted.map((id) => (
              <li key={id}>
                <a
                  className="underline underline-offset-4"
                  href={`/daily-tracks/${encodeURIComponent(id)}`}
                >
                  {items?.find((item) => item.id === id)?.seed_name ?? id}
                </a>
              </li>
            ))}
          </ul>
        ) : null}
        {choice && items ? (
          <FieldSet>
            <FieldLegend className="sr-only">{t("selectionTitle")}</FieldLegend>
            <FieldGroup className="max-h-80 overflow-auto">
              {items.map((item) => (
                <Field key={item.id} orientation="horizontal">
                  <Checkbox
                    id={`quota-${item.id}`}
                    checked={selection.includes(item.id)}
                    disabled={
                      item.id === choice.targetId ||
                      (!selection.includes(item.id) &&
                        selection.length >= choice.limit)
                    }
                    onCheckedChange={(checked) =>
                      setSelection((current) =>
                        checked
                          ? [...current, item.id]
                          : current.filter((id) => id !== item.id),
                      )
                    }
                  />
                  <FieldLabel htmlFor={`quota-${item.id}`}>
                    {item.seed_name ?? item.id}
                  </FieldLabel>
                </Field>
              ))}
            </FieldGroup>
          </FieldSet>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => close(null)}>
            {t("back")}
          </Button>
          {restricted ? (
            <Button nativeButton={false} render={<a href="/billing" />}>
              {t("title")}
            </Button>
          ) : (
            <Button
              disabled={!items || selection.length !== choice?.limit || failed}
              onClick={() => close(selection)}
            >
              {t("selectionConfirm")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
  return {
    choose,
    dialog,
    showRestriction: (ids: string[]) => {
      setItems(null);
      setFailed(false);
      setRestricted(ids);
    },
  };
}
