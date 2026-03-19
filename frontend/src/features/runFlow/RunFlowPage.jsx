import React, { useCallback, useEffect, useMemo, useState } from 'react';

import ExtractionWaitingPage from './ExtractionWaitingPage';
import PostExtractionReviewPage from './PostExtractionReviewPage';
import RunSetupPage from './RunSetupPage';
import RunWorkspace from './RunWorkspace';
import SummaryWaitingPage from './SummaryWaitingPage';
import { buildInitialRunCaseState } from './runSnapshot';
import {
    fetchRun,
    fetchRunChecklist,
    fetchRunDocuments,
    fetchRunSummaryStatus,
    startRunExtraction,
    startRunSummary,
    updateRunChecklist,
    updateRunWorkflowStage
} from '../../services/apiClient';

const EMPTY_SESSION = {
    runId: '',
    caseTitle: '',
    sourceCaseId: '',
    extractionConfig: null,
    summaryConfig: null,
    documents: [],
    checklistCategories: [],
    summaryText: '',
    runData: null
};

const WORKFLOW_STAGES = new Set(['setup', 'extraction_wait', 'review', 'summary_wait', 'workspace']);

function normalizeWorkflowStage(value) {
    const text = String(value || '').trim();
    if (!WORKFLOW_STAGES.has(text)) {
        return null;
    }
    return text;
}

function deriveStage(extractionStatus, summaryStatus, workflowStage) {
    if (summaryStatus === 'queued' || summaryStatus === 'running') {
        return 'summary_wait';
    }
    if (extractionStatus === 'queued' || extractionStatus === 'running') {
        return 'extraction_wait';
    }
    const persistedStage = normalizeWorkflowStage(workflowStage);
    if (persistedStage) {
        return persistedStage;
    }
    if (summaryStatus === 'succeeded') {
        return 'workspace';
    }
    if (summaryStatus === 'failed') {
        return 'review';
    }
    if (extractionStatus === 'succeeded') {
        return 'review';
    }
    return 'setup';
}

const RunFlowPage = ({ runId }) => {
    const [stage, setStage] = useState('loading');
    const [session, setSession] = useState({ ...EMPTY_SESSION, runId });
    const [globalError, setGlobalError] = useState('');

    const hydrateRun = useCallback(async () => {
        if (!runId) {
            setGlobalError('Run ID is required.');
            setStage('error');
            return;
        }

        setGlobalError('');
        setStage('loading');

        try {
            const runPayload = await fetchRun(runId);
            const extractionStatus = String(runPayload?.extractionStatus ?? runPayload?.extraction_status ?? 'not_started');
            const summaryStatus = String(runPayload?.summaryStatus ?? runPayload?.summary_status ?? 'not_started');
            const workflowStage = runPayload?.workflowStage ?? runPayload?.workflow_stage ?? null;

            const caseTitle = String(runPayload?.caseTitle ?? runPayload?.case_title ?? '').trim();
            const sourceCaseId = String(runPayload?.sourceCaseId ?? runPayload?.source_case_id ?? '').trim();
            const extractionConfig = runPayload?.extractionConfig ?? runPayload?.extraction_config ?? null;
            const summaryConfig = runPayload?.summaryConfig ?? runPayload?.summary_config ?? null;

            let documents = [];
            let checklistCategories = [];
            let summaryText = '';

            const shouldLoadExtractionOutputs =
                extractionStatus === 'succeeded' ||
                summaryStatus === 'queued' ||
                summaryStatus === 'running' ||
                summaryStatus === 'succeeded' ||
                summaryStatus === 'failed';

            if (shouldLoadExtractionOutputs) {
                const [documentsPayload, checklistPayload] = await Promise.all([
                    fetchRunDocuments(runId),
                    fetchRunChecklist(runId)
                ]);
                documents = Array.isArray(documentsPayload) ? documentsPayload : [];
                checklistCategories = Array.isArray(checklistPayload?.categories) ? checklistPayload.categories : [];
            }

            if (summaryStatus === 'succeeded') {
                const summaryPayload = await fetchRunSummaryStatus(runId);
                summaryText = String(summaryPayload?.summaryText ?? summaryPayload?.summary_text ?? '');
            }

            setSession({
                runId,
                caseTitle,
                sourceCaseId,
                extractionConfig,
                summaryConfig,
                documents,
                checklistCategories,
                summaryText,
                runData: runPayload
            });
            setStage(deriveStage(extractionStatus, summaryStatus, workflowStage));
        } catch (error) {
            setGlobalError(error?.message || `Failed to load run '${runId}'.`);
            setStage('error');
        }
    }, [runId]);

    useEffect(() => {
        void hydrateRun();
    }, [hydrateRun]);

    const handleRunDataUpdated = useCallback((runPayload) => {
        if (!runPayload) {
            return;
        }
        const caseTitle = String(runPayload?.caseTitle ?? runPayload?.case_title ?? '').trim();
        const sourceCaseId = String(runPayload?.sourceCaseId ?? runPayload?.source_case_id ?? '').trim();
        const extractionConfig = runPayload?.extractionConfig ?? runPayload?.extraction_config ?? null;
        const summaryConfig = runPayload?.summaryConfig ?? runPayload?.summary_config ?? null;
        setSession((current) => ({
            ...current,
            caseTitle,
            sourceCaseId,
            extractionConfig,
            summaryConfig,
            runData: runPayload
        }));
    }, []);

    const handleBackToSetup = useCallback(async () => {
        const payload = await updateRunWorkflowStage(runId, 'setup');
        handleRunDataUpdated(payload);
        setGlobalError('');
        setStage('setup');
    }, [handleRunDataUpdated, runId]);

    const handleBackToReview = useCallback(async () => {
        const payload = await updateRunWorkflowStage(runId, 'review');
        handleRunDataUpdated(payload);
        setGlobalError('');
        setStage('review');
    }, [handleRunDataUpdated, runId]);

    const handleStartExtraction = useCallback(async ({ runData, extractionConfig, summaryConfig }) => {
        const nextRunData = runData || session.runData;
        if (!nextRunData) {
            throw new Error('Run metadata is missing. Reload this run and try again.');
        }
        await startRunExtraction(runId, extractionConfig);
        const caseTitle = String(nextRunData?.caseTitle ?? nextRunData?.case_title ?? session.caseTitle).trim();
        const sourceCaseId = String(nextRunData?.sourceCaseId ?? nextRunData?.source_case_id ?? session.sourceCaseId).trim();
        setGlobalError('');
        setSession((current) => ({
            ...current,
            caseTitle,
            sourceCaseId,
            extractionConfig,
            summaryConfig,
            runData: nextRunData
        }));
        setStage('extraction_wait');
    }, [runId, session.caseTitle, session.runData, session.sourceCaseId]);

    const handleExtractionCompleted = useCallback(async () => {
        try {
            const [runPayload, documentsPayload, checklistPayload] = await Promise.all([
                fetchRun(runId),
                fetchRunDocuments(runId),
                fetchRunChecklist(runId)
            ]);
            const caseTitle = String(runPayload?.caseTitle ?? runPayload?.case_title ?? '').trim();
            const sourceCaseId = String(runPayload?.sourceCaseId ?? runPayload?.source_case_id ?? '').trim();
            const documents = Array.isArray(documentsPayload) ? documentsPayload : [];
            const categories = Array.isArray(checklistPayload?.categories) ? checklistPayload.categories : [];
            const extractionConfig = runPayload?.extractionConfig ?? runPayload?.extraction_config ?? session.extractionConfig;
            const summaryConfig = runPayload?.summaryConfig ?? runPayload?.summary_config ?? session.summaryConfig;

            setSession((current) => ({
                ...current,
                caseTitle,
                sourceCaseId,
                extractionConfig,
                summaryConfig,
                documents,
                checklistCategories: categories,
                runData: runPayload
            }));
            setStage('review');
        } catch (error) {
            setGlobalError(error?.message || 'Failed to load extraction outputs.');
            setStage('setup');
        }
    }, [runId, session.extractionConfig, session.summaryConfig]);

    const handleExtractionFailed = useCallback((failedStage) => {
        const message = String(failedStage?.error || 'Extraction failed.');
        setGlobalError(message);
        setStage('setup');
    }, []);

    const handleStartSummary = useCallback(async (checklistCategories) => {
        if (!runId) {
            throw new Error('Run ID is missing; cannot start summary.');
        }
        const payload = await updateRunChecklist(runId, {
            categories: Array.isArray(checklistCategories) ? checklistCategories : []
        });
        const persistedCategories = Array.isArray(payload?.categories) ? payload.categories : [];
        await startRunSummary(runId, session.summaryConfig);
        setSession((current) => ({
            ...current,
            checklistCategories: persistedCategories
        }));
        setStage('summary_wait');
    }, [runId, session.summaryConfig]);

    const handleSummaryCompleted = useCallback(async (summaryPayload) => {
        const summaryText = String(summaryPayload?.summaryText ?? summaryPayload?.summary_text ?? '');
        setSession((current) => ({
            ...current,
            summaryText
        }));
        setStage('workspace');
    }, []);

    const handleSummaryFailed = useCallback((failedStage) => {
        const message = String(failedStage?.error || 'Summary generation failed.');
        setGlobalError(message);
        setStage('review');
    }, []);

    const initialCaseState = useMemo(
        () => buildInitialRunCaseState({
            runId: session.runId,
            sourceCaseId: session.sourceCaseId,
            documents: session.documents,
            checklistCategories: session.checklistCategories,
            summaryText: session.summaryText
        }),
        [
            session.checklistCategories,
            session.documents,
            session.runId,
            session.sourceCaseId,
            session.summaryText
        ]
    );

    if (stage === 'loading') {
        return (
            <div className="min-h-screen bg-[var(--color-surface-app)] text-[var(--color-text-primary)] flex items-center justify-center p-6">
                <div className="w-full max-w-xl rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-panel)] shadow-lg p-8">
                    <p className="text-sm text-[var(--color-text-muted)]">Loading run {runId}…</p>
                </div>
            </div>
        );
    }

    if (stage === 'error') {
        return (
            <div className="min-h-screen bg-[var(--color-surface-app)] text-[var(--color-text-primary)] flex items-center justify-center p-6">
                <div className="w-full max-w-xl rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-panel)] shadow-lg p-8 space-y-4">
                    <p className="text-sm text-[var(--color-text-danger)]">{globalError || 'Failed to load run.'}</p>
                    <button
                        type="button"
                        onClick={() => {
                            void hydrateRun();
                        }}
                        className="rounded bg-[var(--color-accent)] px-4 py-2 text-sm font-semibold text-[var(--color-text-inverse)] hover:bg-[var(--color-accent-hover)]"
                    >
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    if (stage === 'setup') {
        return (
            <>
                {globalError && (
                    <div className="bg-[var(--color-danger-soft)] border-b border-[var(--color-danger-soft)] px-4 py-2 text-sm text-[var(--color-text-danger)]">
                        {globalError}
                    </div>
                )}
                <RunSetupPage
                    runId={runId}
                    initialRunData={session.runData}
                    onRunDataUpdated={handleRunDataUpdated}
                    onStartExtraction={handleStartExtraction}
                />
            </>
        );
    }

    if (stage === 'extraction_wait') {
        return (
            <ExtractionWaitingPage
                key={`extract-${session.runId}`}
                runId={session.runId}
                caseTitle={session.caseTitle}
                onCompleted={handleExtractionCompleted}
                onFailed={handleExtractionFailed}
            />
        );
    }

    if (stage === 'review') {
        return (
            <PostExtractionReviewPage
                key={`review-${session.runId}`}
                runId={session.runId}
                caseTitle={session.caseTitle}
                initialCaseState={initialCaseState}
                onStartSummary={handleStartSummary}
                onBackToSetup={handleBackToSetup}
            />
        );
    }

    if (stage === 'summary_wait') {
        return (
            <SummaryWaitingPage
                key={`summary-${session.runId}`}
                runId={session.runId}
                caseTitle={session.caseTitle}
                onCompleted={handleSummaryCompleted}
                onFailed={handleSummaryFailed}
            />
        );
    }

    return (
        <RunWorkspace
            key={`workspace-${session.runId}`}
            runId={session.runId}
            caseTitle={session.caseTitle}
            initialCaseState={initialCaseState}
            onBackToReview={handleBackToReview}
        />
    );
};

export default RunFlowPage;
