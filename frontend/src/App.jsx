import React, { useMemo, useState } from 'react';

import HomeScreen from './features/home/HomeScreen';
import ExtractionWaitingPage from './features/runFlow/ExtractionWaitingPage';
import PostExtractionReviewPage from './features/runFlow/PostExtractionReviewPage';
import RunWorkspace from './features/runFlow/RunWorkspace';
import SummaryWaitingPage from './features/runFlow/SummaryWaitingPage';
import { buildInitialRunCaseState } from './features/runFlow/runSnapshot';
import { fetchRun, fetchRunChecklist, fetchRunDocuments, updateRunChecklist } from './services/apiClient';

const EMPTY_SESSION = {
    runId: '',
    caseTitle: '',
    sourceCaseId: '',
    extractionConfig: null,
    summaryConfig: null,
    documents: [],
    checklistCategories: [],
    summaryText: ''
};

const App = () => {
    const [stage, setStage] = useState('setup');
    const [session, setSession] = useState(EMPTY_SESSION);
    const [globalError, setGlobalError] = useState('');

    const handleStartExtraction = async ({ runData, extractionConfig, summaryConfig }) => {
        const runId = String(runData?.runId ?? runData?.run_id ?? '').trim();
        if (!runId) {
            throw new Error('Run ID is missing from run initialization response.');
        }
        const caseTitle = String(runData?.caseTitle ?? runData?.case_title ?? '').trim();
        const sourceCaseId = String(runData?.sourceCaseId ?? runData?.source_case_id ?? '').trim();
        setGlobalError('');
        setSession({
            runId,
            caseTitle,
            sourceCaseId,
            extractionConfig,
            summaryConfig,
            documents: [],
            checklistCategories: [],
            summaryText: ''
        });
        setStage('extraction_wait');
    };

    const handleExtractionCompleted = async () => {
        try {
            const [runPayload, documentsPayload, checklistPayload] = await Promise.all([
                fetchRun(session.runId),
                fetchRunDocuments(session.runId),
                fetchRunChecklist(session.runId)
            ]);
            const caseTitle = String(runPayload?.caseTitle ?? runPayload?.case_title ?? session.caseTitle).trim();
            const sourceCaseId = String(runPayload?.sourceCaseId ?? runPayload?.source_case_id ?? session.sourceCaseId).trim();
            const documents = Array.isArray(documentsPayload) ? documentsPayload : [];
            const categories = Array.isArray(checklistPayload?.categories) ? checklistPayload.categories : [];

            setSession((current) => ({
                ...current,
                caseTitle,
                sourceCaseId,
                documents,
                checklistCategories: categories
            }));
            setStage('review');
        } catch (error) {
            setGlobalError(error?.message || 'Failed to load extraction outputs.');
            setStage('setup');
        }
    };

    const handleSummaryCompleted = async (summaryPayload) => {
        const text = String(summaryPayload?.summaryText ?? summaryPayload?.summary_text ?? '');
        setSession((current) => ({
            ...current,
            summaryText: text
        }));
        setStage('workspace');
    };

    const handleStartSummary = async (checklistCategories) => {
        if (!session.runId) {
            throw new Error('Run ID is missing; cannot start summary.');
        }
        const payload = await updateRunChecklist(session.runId, {
            categories: Array.isArray(checklistCategories) ? checklistCategories : []
        });
        const persistedCategories = Array.isArray(payload?.categories) ? payload.categories : [];
        setSession((current) => ({
            ...current,
            checklistCategories: persistedCategories
        }));
        setStage('summary_wait');
    };

    const initialCaseState = useMemo(
        () => buildInitialRunCaseState({
            runId: session.runId,
            sourceCaseId: session.sourceCaseId,
            documents: session.documents,
            checklistCategories: session.checklistCategories,
            summaryText: session.summaryText
        }),
        [session.checklistCategories, session.documents, session.runId, session.sourceCaseId, session.summaryText]
    );

    if (stage === 'extraction_wait') {
        return (
            <ExtractionWaitingPage
                key={`extract-${session.runId}`}
                runId={session.runId}
                caseTitle={session.caseTitle}
                extractionConfig={session.extractionConfig}
                onCompleted={handleExtractionCompleted}
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
            />
        );
    }

    if (stage === 'summary_wait') {
        return (
            <SummaryWaitingPage
                key={`summary-${session.runId}`}
                runId={session.runId}
                caseTitle={session.caseTitle}
                summaryConfig={session.summaryConfig}
                onCompleted={handleSummaryCompleted}
            />
        );
    }

    if (stage === 'workspace') {
        return (
            <RunWorkspace
                key={`workspace-${session.runId}`}
                runId={session.runId}
                caseTitle={session.caseTitle}
                initialCaseState={initialCaseState}
            />
        );
    }

    return (
        <>
            {globalError && (
                <div className="bg-[var(--color-danger-soft)] border-b border-[var(--color-danger-soft)] px-4 py-2 text-sm text-[var(--color-text-danger)]">
                    {globalError}
                </div>
            )}
            <HomeScreen onStartExtraction={handleStartExtraction} />
        </>
    );
};

export default App;
