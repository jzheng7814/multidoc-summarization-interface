import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchChecklistStatus, startChecklistExtraction } from '../../services/apiClient';

const ACTIVE_STATUSES = new Set(['pending', 'queued', 'preprocessing', 'waiting_resources', 'running', 'finalizing']);
const FAILURE_STATUSES = new Set(['failed', 'error']);

const normaliseStatus = (payload) => ({
    checklistStatus: String(payload?.checklistStatus ?? payload?.checklist_status ?? 'pending').trim() || 'pending',
    statusMessage: payload?.statusMessage ?? payload?.status_message ?? null,
    phase: payload?.phase ?? null,
    slurmState: payload?.slurmState ?? payload?.slurm_state ?? null,
    currentStep: payload?.currentStep ?? payload?.current_step ?? null,
    maxSteps: payload?.maxSteps ?? payload?.max_steps ?? null,
    error: payload?.error ?? null
});

const buildProgressLabel = (status) => {
    const phase = status.phase || status.checklistStatus;
    const stepPart =
        status.currentStep != null && status.maxSteps != null
            ? `Step ${status.currentStep} of ${status.maxSteps}`
            : status.currentStep != null
                ? `Step ${status.currentStep}`
                : null;

    if (status.statusMessage) {
        return stepPart ? `${status.statusMessage} (${stepPart})` : status.statusMessage;
    }
    if (stepPart) {
        return `${phase} (${stepPart})`;
    }
    if (status.slurmState) {
        return `${phase} (${status.slurmState})`;
    }
    return phase;
};

const ChecklistPreparationPage = ({ caseId, onReady, onBack }) => {
    const [status, setStatus] = useState(() => normaliseStatus({ checklistStatus: 'pending' }));
    const [isBusy, setIsBusy] = useState(false);
    const pollTimeoutRef = useRef(null);
    const isMountedRef = useRef(true);

    const clearPollTimeout = useCallback(() => {
        if (pollTimeoutRef.current) {
            window.clearTimeout(pollTimeoutRef.current);
            pollTimeoutRef.current = null;
        }
    }, []);

    const handleStatus = useCallback((payload) => {
        const next = normaliseStatus(payload);
        if (!isMountedRef.current) {
            return next;
        }
        setStatus(next);
        if (next.checklistStatus === 'ready') {
            clearPollTimeout();
            onReady?.();
        }
        return next;
    }, [clearPollTimeout, onReady]);

    const pollStatus = useCallback(async () => {
        try {
            const payload = await fetchChecklistStatus(caseId);
            const next = handleStatus(payload);
            if (!isMountedRef.current) {
                return;
            }
            if (ACTIVE_STATUSES.has(next.checklistStatus)) {
                pollTimeoutRef.current = window.setTimeout(() => {
                    void pollStatus();
                }, 2000);
            }
        } catch (error) {
            if (!isMountedRef.current) {
                return;
            }
            setStatus((current) => ({
                ...current,
                checklistStatus: 'failed',
                error: error.message || 'Failed to poll checklist status.',
                statusMessage: 'Failed to poll checklist status.'
            }));
        }
    }, [caseId, handleStatus]);

    const startAndMonitor = useCallback(async () => {
        setIsBusy(true);
        clearPollTimeout();
        try {
            const payload = await startChecklistExtraction(caseId);
            const next = handleStatus(payload);
            if (!isMountedRef.current) {
                return;
            }
            if (ACTIVE_STATUSES.has(next.checklistStatus)) {
                pollTimeoutRef.current = window.setTimeout(() => {
                    void pollStatus();
                }, 1000);
            }
        } catch (error) {
            if (!isMountedRef.current) {
                return;
            }
            setStatus({
                checklistStatus: 'failed',
                statusMessage: 'Failed to start checklist extraction.',
                phase: 'failed',
                slurmState: null,
                currentStep: null,
                maxSteps: null,
                error: error.message || 'Failed to start checklist extraction.'
            });
        } finally {
            if (isMountedRef.current) {
                setIsBusy(false);
            }
        }
    }, [caseId, clearPollTimeout, handleStatus, pollStatus]);

    useEffect(() => {
        isMountedRef.current = true;
        void startAndMonitor();
        return () => {
            isMountedRef.current = false;
            clearPollTimeout();
        };
    }, [clearPollTimeout, startAndMonitor]);

    const isFailed = FAILURE_STATUSES.has(status.checklistStatus);
    const progressLabel = useMemo(() => buildProgressLabel(status), [status]);

    return (
        <div className="min-h-screen bg-[var(--color-surface-app)] text-[var(--color-text-primary)] flex items-center justify-center p-6">
            <div className="w-full max-w-2xl rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-panel)] shadow-lg p-8">
                <div className="flex items-center justify-between gap-3 mb-5">
                    <h1 className="text-xl font-semibold">Preparing Checklist Extraction</h1>
                    <span className="rounded-full border border-[var(--color-border-strong)] bg-[var(--color-surface-panel-alt)] px-3 py-1 text-xs font-medium text-[var(--color-text-secondary)]">
                        Case ID: {caseId}
                    </span>
                </div>

                <div className="flex items-center gap-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] p-4">
                    <div className="h-8 w-8 rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-accent)] animate-spin" />
                    <div className="min-w-0">
                        <p className="text-sm font-medium text-[var(--color-text-primary)]">{progressLabel}</p>
                        {status.slurmState && (
                            <p className="text-xs text-[var(--color-text-muted)] mt-1">Cluster state: {status.slurmState}</p>
                        )}
                    </div>
                </div>

                {status.error && (
                    <div className="mt-4 rounded-md border border-[var(--color-danger-soft)] bg-[var(--color-danger-soft)] px-3 py-2 text-sm text-[var(--color-text-danger)]">
                        {status.error}
                    </div>
                )}

                <div className="mt-6 flex items-center justify-end gap-2">
                    <button
                        type="button"
                        onClick={onBack}
                        className="px-3 py-1.5 text-sm rounded border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]"
                    >
                        Back
                    </button>
                    {isFailed && (
                        <button
                            type="button"
                            onClick={() => {
                                void startAndMonitor();
                            }}
                            disabled={isBusy}
                            className="px-3 py-1.5 text-sm rounded bg-[var(--color-accent)] text-[var(--color-text-inverse)] hover:bg-[var(--color-accent-hover)] disabled:opacity-60"
                        >
                            {isBusy ? 'Retrying…' : 'Retry'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ChecklistPreparationPage;
