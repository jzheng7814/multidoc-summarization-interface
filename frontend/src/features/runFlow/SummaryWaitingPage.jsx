import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { fetchRunSummaryStatus } from '../../services/apiClient';

const ACTIVE_STATUSES = new Set(['queued', 'running']);

function parseSummaryStage(payload) {
    const stage = payload?.summary ?? payload ?? {};
    return {
        status: String(stage?.status || 'queued'),
        phase: stage?.phase || stage?.eventType || null,
        slurmState: stage?.slurmState ?? null,
        currentStep: stage?.currentStep ?? null,
        maxSteps: stage?.maxSteps ?? null,
        toolName: stage?.toolName ?? null,
        toolSuccess: stage?.toolSuccess ?? null,
        error: stage?.error || null
    };
}

function buildStatusLabel(stage, dotCount) {
    const dots = '.'.repeat(dotCount);
    if (stage.status === 'queued') {
        return `Queued${dots}`;
    }
    if (stage.phase) {
        return `${stage.phase}${dots}`;
    }
    return `Running${dots}`;
}

const SummaryWaitingPage = ({
    runId,
    title,
    onCompleted,
    onFailed
}) => {
    const [stage, setStage] = useState(() => parseSummaryStage({ status: 'queued' }));
    const [localError, setLocalError] = useState('');
    const [dotCount, setDotCount] = useState(1);
    const pollTimeoutRef = useRef(null);
    const isMountedRef = useRef(true);

    const clearPollTimeout = useCallback(() => {
        if (pollTimeoutRef.current) {
            window.clearTimeout(pollTimeoutRef.current);
            pollTimeoutRef.current = null;
        }
    }, []);

    const handleStagePayload = useCallback((payload) => {
        const next = parseSummaryStage(payload);
        setStage(next);
        return next;
    }, []);

    const pollStatus = useCallback(async () => {
        try {
            const payload = await fetchRunSummaryStatus(runId);
            if (!isMountedRef.current) {
                return;
            }
            const next = handleStagePayload(payload);
            if (next.status === 'succeeded') {
                clearPollTimeout();
                await onCompleted?.(payload);
                return;
            }
            if (next.status === 'failed') {
                clearPollTimeout();
                await onFailed?.(next);
                return;
            }
            if (ACTIVE_STATUSES.has(next.status)) {
                pollTimeoutRef.current = window.setTimeout(() => {
                    void pollStatus();
                }, 2000);
            }
        } catch (error) {
            if (!isMountedRef.current) {
                return;
            }
            setLocalError(error?.message || 'Failed to poll summary status.');
        }
    }, [clearPollTimeout, handleStagePayload, onCompleted, onFailed, runId]);

    useEffect(() => {
        isMountedRef.current = true;
        setLocalError('');
        void pollStatus();
        return () => {
            isMountedRef.current = false;
            clearPollTimeout();
        };
    }, [clearPollTimeout, pollStatus]);

    useEffect(() => {
        const intervalId = window.setInterval(() => {
            setDotCount((current) => (current % 3) + 1);
        }, 500);
        return () => window.clearInterval(intervalId);
    }, []);

    const statusLabel = useMemo(() => buildStatusLabel(stage, dotCount), [dotCount, stage]);

    return (
        <div className="min-h-screen bg-[var(--color-surface-app)] text-[var(--color-text-primary)] flex items-center justify-center p-6">
            <div className="w-full max-w-3xl rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-panel)] shadow-lg p-8">
                <div className="flex items-center justify-between gap-4 mb-5">
                    <div>
                        <h1 className="text-xl font-semibold">Running Summarization</h1>
                        <p className="text-sm text-[var(--color-text-muted)] mt-1">
                            {title ? `Title: ${title}` : 'Summary run is in progress.'}
                        </p>
                    </div>
                    <span className="rounded-full border border-[var(--color-border-strong)] bg-[var(--color-surface-panel-alt)] px-3 py-1 text-xs font-medium text-[var(--color-text-secondary)]">
                        Run ID: {runId}
                    </span>
                </div>

                <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] p-4">
                    <div className="flex items-center gap-4">
                        <div className="h-8 w-8 rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-accent)] animate-spin" />
                        <div className="min-w-0">
                            <p className="text-sm font-medium text-[var(--color-text-primary)]">{statusLabel}</p>
                            {stage.slurmState && (
                                <p className="text-xs text-[var(--color-text-muted)] mt-1">SLURM: {stage.slurmState}</p>
                            )}
                        </div>
                    </div>

                    <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-[var(--color-text-secondary)]">
                        <div>
                            Step: {stage.currentStep != null ? (stage.maxSteps != null ? `${stage.currentStep} / ${stage.maxSteps}` : String(stage.currentStep)) : '—'}
                        </div>
                        <div>
                            Tool: {stage.toolName ? `${stage.toolName}${stage.toolSuccess === true ? ' (ok)' : stage.toolSuccess === false ? ' (failed)' : ''}` : '—'}
                        </div>
                    </div>
                </div>

                {(stage.error || localError) && (
                    <div className="mt-4 rounded-md border border-[var(--color-danger-soft)] bg-[var(--color-danger-soft)] px-3 py-2 text-sm text-[var(--color-text-danger)]">
                        {stage.error || localError}
                    </div>
                )}
            </div>
        </div>
    );
};

export default SummaryWaitingPage;
