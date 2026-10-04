import { useEffect, useRef, useState } from "react";
import * as client from "./operatorMutationClient";
import { OperatorPageNotFoundError } from "./operatorDirectoryClient";

type Families = {
  dataset: { request: client.DatasetRefreshRequest; operation: client.DatasetRefreshOperation };
  financial: { request: client.FinancialRefreshRequest; operation: client.FinancialRefreshOperation };
  industry: { request: client.IndustryRefreshRequest; operation: client.IndustryRefreshOperation };
};
type Kind = keyof Families;
type RefreshRequest<K extends Kind> = Families[K]["request"];
type RefreshOperation<K extends Kind> = Families[K]["operation"];
type Transport<K extends Kind> = {
  proof: (request: RefreshRequest<K>, signal: AbortSignal) => Promise<{ proof: string }>;
  submit: (request: RefreshRequest<K>, proof: string, signal: AbortSignal) => Promise<RefreshOperation<K>>;
  load: (request: RefreshRequest<K>, signal: AbortSignal) => Promise<RefreshOperation<K>>;
  request: (operation: RefreshOperation<K>) => RefreshRequest<K>;
};
// Calls retain the checked client and its live functions (including test stand-ins).
const transports: { [K in Kind]: Transport<K> } = {
  dataset: {
    proof: (...args) => client.confirmDatasetRefreshProof(...args), submit: (...args) => client.submitDatasetRefresh(...args),
    load: (...args) => client.loadDatasetRefresh(...args), request: operation => ({ asOf: operation.asOf, idempotencyKey: operation.idempotencyKey }),
  },
  financial: {
    proof: (...args) => client.confirmFinancialRefreshProof(...args), submit: (...args) => client.submitFinancialRefresh(...args),
    load: (...args) => client.loadFinancialRefresh(...args), request: operation => ({ observationThroughSession: operation.observationThroughSession, idempotencyKey: operation.idempotencyKey }),
  },
  industry: {
    proof: (...args) => client.confirmIndustryRefreshProof(...args), submit: (...args) => client.submitIndustryRefresh(...args),
    load: (...args) => client.loadIndustryRefresh(...args), request: operation => ({ observationThroughSession: operation.observationThroughSession, idempotencyKey: operation.idempotencyKey }),
  },
};
export type RefreshSubmissionFailure<K extends Kind> =
  | { kind: "rejected"; code: "conflict" | "request-invalid"; request: RefreshRequest<K> }
  | { kind: "failed"; reason: unknown }
  | { kind: "stopped" };
const terminal = (operation: Families[Kind]["operation"]) => operation.status === "succeeded" || operation.status === "failed" || operation.status === "cancelled";
function uncertain(reason: unknown): boolean {
  if (reason instanceof DOMException && reason.name === "AbortError") return true;
  if (reason instanceof OperatorPageNotFoundError) return false;
  return !(reason instanceof client.OperatorMutationError) || reason.code === "unavailable";
}

/** Owns Data Refresh acceptance, response fencing and visibility-aware receipt polling. */
export function useDataRefresh<K extends Kind>(kind: K, {
  onAccessNotFound, onOperationAccepted,
}: { onAccessNotFound: () => void; onOperationAccepted: () => void }) {
  const transport = transports[kind];
  const [confirmation, setConfirmation] = useState<{ request: RefreshRequest<K>; submitting: boolean; error: unknown | null } | null>(null);
  const [pending, setPending] = useState<{ generation: number; request: RefreshRequest<K> } | null>(null);
  const [accepted, setAccepted] = useState<{ generation: number; operation: RefreshOperation<K> } | null>(null);
  const [pollError, setPollError] = useState(false);
  const [submissionFailure, setSubmissionFailure] = useState<RefreshSubmissionFailure<K> | null>(null);
  const submissionGeneration = useRef(0);
  const operationGeneration = useRef(0);
  const mounted = useRef(true);
  const active = useRef<{ generation: number; phase: "proof" | "submission"; controller: AbortController; dismissed: boolean } | null>(null);
  const confirmationRef = useRef(confirmation);
  const pendingRef = useRef(pending);
  confirmationRef.current = confirmation;
  pendingRef.current = pending;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false; submissionGeneration.current++; operationGeneration.current++;
      const run = active.current;
      if (run && (!run.dismissed || run.phase !== "submission")) run.controller.abort();
    };
  }, []);

  function replaceOperation(operation: RefreshOperation<K>) {
    setAccepted({ generation: ++operationGeneration.current, operation });
  }
  function accept(operation: RefreshOperation<K>) {
    submissionGeneration.current++;
    active.current = null;
    setConfirmation(null); setPending(null); setPollError(false); setSubmissionFailure(null);
    replaceOperation(operation);
    onOperationAccepted();
  }
  function reject(request: RefreshRequest<K>, code: "conflict" | "request-invalid") {
    submissionGeneration.current++;
    setConfirmation(null); setPending(null);
    setSubmissionFailure({ kind: "rejected", code, request });
  }
  function reconcile(request: RefreshRequest<K>, generation: number) {
    setConfirmation(null);
    operationGeneration.current++;
    setAccepted(null); setPending({ generation, request }); setPollError(false); setSubmissionFailure(null);
  }

  useEffect(() => {
    const tracked = pending ? { ...pending, source: "pending" as const }
      : accepted && !terminal(accepted.operation) ? { generation: accepted.generation, request: transport.request(accepted.operation), source: "operation" as const } : null;
    if (!tracked) return;
    let disposed = false;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    const current = () => !disposed && (tracked.source === "pending"
      ? tracked.generation === submissionGeneration.current : tracked.generation === operationGeneration.current);
    const schedule = (delay = 5000) => {
      if (disposed || document.visibilityState !== "visible") return;
      window.clearTimeout(timer); timer = window.setTimeout(() => void poll(), delay);
    };
    const poll = async () => {
      if (!current() || document.visibilityState !== "visible") return;
      controller?.abort();
      const requestController = new AbortController(); controller = requestController;
      try {
        const next = await transport.load(tracked.request, requestController.signal);
        if (!current() || requestController.signal.aborted) return;
        setPollError(false);
        if (tracked.source === "pending") accept(next);
        else setAccepted({ generation: tracked.generation, operation: next });
        if (!terminal(next)) schedule();
      } catch (reason) {
        if (!current() || requestController.signal.aborted || (reason instanceof DOMException && reason.name === "AbortError")) return;
        if (reason instanceof OperatorPageNotFoundError && tracked.source === "operation") {
          operationGeneration.current++; setAccepted(null); onAccessNotFound(); return;
        }
        if (tracked.source === "pending" && reason instanceof client.OperatorMutationError
          && (reason.code === "conflict" || reason.code === "request-invalid")) {
          reject(tracked.request, reason.code); return;
        }
        setPollError(true); schedule();
      }
    };
    const visibilityChanged = () => {
      if (document.visibilityState === "visible") schedule(0);
      else { window.clearTimeout(timer); controller?.abort(); }
    };
    document.addEventListener("visibilitychange", visibilityChanged); schedule();
    return () => { disposed = true; window.clearTimeout(timer); controller?.abort(); document.removeEventListener("visibilitychange", visibilityChanged); };
  }, [accepted, pending, transport, onAccessNotFound, onOperationAccepted]);

  function review(request: RefreshRequest<K>) {
    if (confirmationRef.current || pendingRef.current) return;
    submissionGeneration.current++;
    setPollError(false); setSubmissionFailure(null); setConfirmation({ request, submitting: false, error: null });
  }
  async function confirm() {
    const selected = confirmationRef.current;
    if (!selected || active.current) return;
    const run = { generation: submissionGeneration.current, phase: "proof" as "proof" | "submission", controller: new AbortController(), dismissed: false };
    active.current = run;
    setConfirmation({ ...selected, submitting: true, error: null });
    const current = () => mounted.current && run.generation === submissionGeneration.current;
    try {
      const proof = await transport.proof(selected.request, run.controller.signal);
      if (!current() || run.dismissed || run.controller.signal.aborted) return;
      run.phase = "submission";
      const operation = await transport.submit(selected.request, proof.proof, run.controller.signal);
      if (current()) accept(operation);
    } catch (reason) {
      if (!current()) return;
      if (run.phase === "submission" && uncertain(reason)) {
        if (!run.dismissed) reconcile(selected.request, run.generation);
        else if (kind === "dataset") setPollError(true);
      } else if (reason instanceof DOMException && reason.name === "AbortError") {
        // Proof is read-only; dismissal already invalidated this completion.
      } else if (reason instanceof client.OperatorMutationError && (reason.code === "conflict" || reason.code === "request-invalid")) {
        reject(selected.request, reason.code);
      } else if (run.dismissed) {
        if (kind === "dataset") setPollError(true);
        else { submissionGeneration.current++; setPending(null); setConfirmation(null); setPollError(false); setSubmissionFailure({ kind: "failed", reason }); }
      } else setConfirmation({ ...selected, submitting: false, error: reason });
    } finally {
      if (active.current === run) active.current = null;
      if (current() && !run.dismissed) setConfirmation(value => value ? { ...value, submitting: false } : null);
    }
  }
  function dismissConfirmation() {
    const run = active.current;
    if (run?.phase === "submission") {
      run.dismissed = true;
      reconcile(confirmationRef.current!.request, run.generation);
    } else {
      submissionGeneration.current++; run?.controller.abort(); active.current = null; setConfirmation(null);
    }
  }
  function retryExact() {
    const selected = pendingRef.current;
    if (!selected) return;
    // Receipt checks do not cancel a submitted mutation; its completion is fenced.
    submissionGeneration.current++; active.current = null;
    setPending(null); setPollError(false); setSubmissionFailure(null);
    setConfirmation({ request: selected.request, submitting: false, error: null });
  }
  function stopChecking() {
    if (!pendingRef.current) return;
    submissionGeneration.current++; active.current = null;
    setPending(null); setPollError(false); setSubmissionFailure({ kind: "stopped" });
  }
  return { confirmation, pendingRequest: pending?.request ?? null, operation: accepted?.operation ?? null,
    pollError, submissionFailure, track: accept, review, confirm, dismissConfirmation, retryExact, stopChecking };
}
