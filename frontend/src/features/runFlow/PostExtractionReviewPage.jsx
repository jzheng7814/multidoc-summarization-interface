import React, { useEffect, useState } from 'react';

import DocumentsPanel from '../workspace/DocumentsPanel';
import ChecklistPanel from '../workspace/components/ChecklistPage';
import WorkspaceStateProvider, { useChecklist, useHighlight } from '../workspace/state/WorkspaceProvider';

const ReviewLayout = ({ runId, title, onStartSummary, onBackToSetup }) => {
    const { setInteractionMode } = useHighlight();
    const { categories } = useChecklist();
    const [isPersisting, setIsPersisting] = useState(false);
    const [isNavigatingBack, setIsNavigatingBack] = useState(false);
    const [actionError, setActionError] = useState('');

    useEffect(() => {
        setInteractionMode('checklist');
    }, [setInteractionMode]);

    const handleStartSummary = async () => {
        setActionError('');
        setIsPersisting(true);
        try {
            await onStartSummary?.(categories);
        } catch (error) {
            setActionError(error?.message || 'Failed to persist checklist edits before summary.');
        } finally {
            setIsPersisting(false);
        }
    };

    const handleBackToSetup = async () => {
        setActionError('');
        setIsNavigatingBack(true);
        try {
            await onBackToSetup?.();
        } catch (error) {
            setActionError(error?.message || 'Failed to return to setup.');
        } finally {
            setIsNavigatingBack(false);
        }
    };

    return (
        <div className="min-h-screen bg-[var(--color-surface-app)] text-[var(--color-text-primary)]">
            <div className="bg-[var(--color-surface-panel)] border-b border-[var(--color-border)] px-6 py-4 shadow-sm">
                <div className="flex items-center justify-between flex-wrap gap-4">
                    <div>
                        <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">Review Checklist Before Summarization</h1>
                        <p className="text-sm text-[var(--color-text-muted)] mt-1">
                            Confirm the extracted checklist contains all synthesis-critical information. Summary is locked until you start summarization.
                        </p>
                        <p className="text-xs text-[var(--color-text-secondary)] mt-1">
                            {title ? `Title: ${title}` : ''} {title ? ' · ' : ''}Run ID: {runId}
                        </p>
                    </div>
                    <div className="flex items-center gap-3">
                        <button
                            type="button"
                            onClick={() => {
                                void handleBackToSetup();
                            }}
                            disabled={isPersisting || isNavigatingBack}
                            className="px-3 py-1.5 text-sm rounded border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]"
                        >
                            {isNavigatingBack ? 'Returning…' : 'Back'}
                        </button>
                        <button
                            type="button"
                            onClick={handleStartSummary}
                            disabled={isPersisting}
                            className="px-3 py-1.5 text-sm rounded bg-[var(--color-accent)] text-[var(--color-text-inverse)] hover:bg-[var(--color-accent-hover)]"
                        >
                            {isPersisting ? 'Saving Checklist…' : 'Start Summarization'}
                        </button>
                    </div>
                </div>
                {actionError && (
                    <div className="mt-3 rounded border border-[var(--color-danger-soft)] bg-[var(--color-danger-soft)] px-3 py-2 text-xs text-[var(--color-text-danger)]">
                        {actionError}
                    </div>
                )}
            </div>

            <div className="flex h-[calc(100vh-96px)] min-h-0 overflow-hidden bg-[var(--color-surface-panel-alt)]">
                <div className="basis-1/2 min-w-0 min-h-0 flex flex-col">
                    <ChecklistPanel isActive />
                </div>
                <div className="basis-1/2 min-w-0 min-h-0 flex flex-col">
                    <DocumentsPanel />
                </div>
            </div>
        </div>
    );
};

const PostExtractionReviewPage = ({
    runId,
    title,
    initialCaseState,
    onStartSummary,
    onBackToSetup
}) => (
    <WorkspaceStateProvider
        runId={initialCaseState?.runId}
        initialCaseState={initialCaseState}
    >
        <ReviewLayout
            runId={runId}
            title={title}
            onStartSummary={onStartSummary}
            onBackToSetup={onBackToSetup}
        />
    </WorkspaceStateProvider>
);

export default PostExtractionReviewPage;
