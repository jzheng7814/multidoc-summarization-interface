import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import DocumentsPanel from '../workspace/DocumentsPanel';
import ChecklistPanel from '../workspace/components/ChecklistPage';
import SummaryPanel from '../workspace/components/SummaryPanel';
import DividerHandle from '../workspace/components/DividerHandle';
import WorkspaceStateProvider, { useHighlight } from '../workspace/state/WorkspaceProvider';

const PANE_ORDER = ['checklist', 'summary', 'documents'];
const MIN_SPLIT = 15;
const MAX_SPLIT = 85;

const RunWorkspaceLayout = ({ runId, title, onBackToReview }) => {
    const [visiblePanes, setVisiblePanes] = useState({
        checklist: true,
        summary: true,
        documents: true
    });
    const [pairSplits, setPairSplits] = useState({
        'checklist-summary': 40,
        'summary-documents': 55,
        'checklist-documents': 45
    });
    const [threeSplit, setThreeSplit] = useState({ first: 30, second: 65 });
    const [isNavigatingBack, setIsNavigatingBack] = useState(false);
    const [backError, setBackError] = useState('');
    const workspaceRef = useRef(null);
    const dragCleanupRef = useRef(null);
    const { setInteractionMode } = useHighlight();

    const activePanes = useMemo(
        () => PANE_ORDER.filter((pane) => visiblePanes[pane]),
        [visiblePanes]
    );

    useEffect(() => {
        setInteractionMode(visiblePanes.summary ? 'canvas' : 'checklist');
    }, [setInteractionMode, visiblePanes.summary]);

    useEffect(() => () => dragCleanupRef.current?.(), []);

    const clampSplit = useCallback((value) => Math.min(MAX_SPLIT, Math.max(MIN_SPLIT, value)), []);

    const togglePane = useCallback((pane) => {
        setVisiblePanes((current) => {
            const next = { ...current, [pane]: !current[pane] };
            if (!Object.values(next).some(Boolean)) {
                return current;
            }
            return next;
        });
    }, []);

    const handleBackToReview = useCallback(async () => {
        setBackError('');
        setIsNavigatingBack(true);
        try {
            await onBackToReview?.();
        } catch (error) {
            setBackError(error?.message || 'Failed to return to checklist review.');
        } finally {
            setIsNavigatingBack(false);
        }
    }, [onBackToReview]);

    const startDragPair = useCallback((pairKey) => (event) => {
        event.preventDefault();
        const handleMouseMove = (moveEvent) => {
            if (!workspaceRef.current) {
                return;
            }
            const rect = workspaceRef.current.getBoundingClientRect();
            if (!rect.width) {
                return;
            }
            const relativeX = moveEvent.clientX - rect.left;
            const percentage = clampSplit((relativeX / rect.width) * 100);
            setPairSplits((current) => ({
                ...current,
                [pairKey]: percentage
            }));
        };
        const handleMouseUp = () => dragCleanupRef.current?.();
        const cleanup = () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
            dragCleanupRef.current = null;
        };
        dragCleanupRef.current?.();
        dragCleanupRef.current = cleanup;
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
    }, [clampSplit]);

    const startDragThree = useCallback((positionKey) => (event) => {
        event.preventDefault();
        const handleMouseMove = (moveEvent) => {
            if (!workspaceRef.current) {
                return;
            }
            const rect = workspaceRef.current.getBoundingClientRect();
            if (!rect.width) {
                return;
            }
            const relativeX = moveEvent.clientX - rect.left;
            const percentage = clampSplit((relativeX / rect.width) * 100);
            setThreeSplit((current) => {
                if (positionKey === 'first') {
                    const maxAllowed = Math.max(MIN_SPLIT, current.second - MIN_SPLIT);
                    return { ...current, first: Math.min(percentage, maxAllowed) };
                }
                const minAllowed = Math.min(MAX_SPLIT, current.first + MIN_SPLIT);
                return { ...current, second: Math.max(percentage, minAllowed) };
            });
        };
        const handleMouseUp = () => dragCleanupRef.current?.();
        const cleanup = () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
            dragCleanupRef.current = null;
        };
        dragCleanupRef.current?.();
        dragCleanupRef.current = cleanup;
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
    }, [clampSplit]);

    const renderPane = (pane) => {
        if (pane === 'checklist') {
            return <ChecklistPanel isActive={visiblePanes.checklist} readOnly />;
        }
        if (pane === 'summary') {
            return <SummaryPanel />;
        }
        return <DocumentsPanel checklistReadOnly />;
    };

    const renderLayout = () => {
        if (activePanes.length === 1) {
            return (
                <div className="flex flex-1 min-w-0 min-h-0">
                    <div className="flex-1 min-w-0 min-h-0 flex flex-col">{renderPane(activePanes[0])}</div>
                </div>
            );
        }

        if (activePanes.length === 2) {
            const pairKey = `${activePanes[0]}-${activePanes[1]}`;
            const split = pairSplits[pairKey] ?? 50;
            return (
                <div className="flex flex-1 min-w-0 min-h-0">
                    <div className="min-w-0 min-h-0 flex flex-col" style={{ flexBasis: `${split}%` }}>
                        {renderPane(activePanes[0])}
                    </div>
                    <DividerHandle onMouseDown={startDragPair(pairKey)} />
                    <div className="min-w-0 min-h-0 flex flex-col" style={{ flexBasis: `${100 - split}%` }}>
                        {renderPane(activePanes[1])}
                    </div>
                </div>
            );
        }

        const middleWidth = Math.max(MIN_SPLIT, threeSplit.second - threeSplit.first);
        return (
            <div className="flex flex-1 min-w-0 min-h-0">
                <div className="min-w-0 min-h-0 flex flex-col" style={{ flexBasis: `${threeSplit.first}%` }}>
                    {renderPane(activePanes[0])}
                </div>
                <DividerHandle onMouseDown={startDragThree('first')} />
                <div className="min-w-0 min-h-0 flex flex-col" style={{ flexBasis: `${middleWidth}%` }}>
                    {renderPane(activePanes[1])}
                </div>
                <DividerHandle onMouseDown={startDragThree('second')} />
                <div className="min-w-0 min-h-0 flex flex-col" style={{ flexBasis: `${100 - threeSplit.second}%` }}>
                    {renderPane(activePanes[2])}
                </div>
            </div>
        );
    };

    return (
        <div className="min-h-screen bg-[var(--color-surface-app)] text-[var(--color-text-primary)] transition-colors">
            <div className="bg-[var(--color-surface-panel)] border-b border-[var(--color-border)] px-6 py-4 shadow-sm">
                <div className="flex items-center justify-between flex-wrap gap-4">
                    <div>
                        <div className="flex items-center gap-3">
                            <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">Run Workspace</h1>
                            <span className="rounded-full border border-[var(--color-border-strong)] bg-[var(--color-surface-panel-alt)] px-2.5 py-1 text-xs font-medium text-[var(--color-text-secondary)]">
                                Run ID: {runId}
                            </span>
                        </div>
                        <p className="text-sm text-[var(--color-text-muted)]">
                            {title ? `Title: ${title}` : 'Review checklist and documents while editing summary drafts.'}
                        </p>
                    </div>
                    <div className="flex items-center gap-3 flex-wrap">
                        <button
                            type="button"
                            onClick={() => {
                                void handleBackToReview();
                            }}
                            disabled={isNavigatingBack}
                            className="rounded border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]"
                        >
                            {isNavigatingBack ? 'Returning…' : 'Back'}
                        </button>
                        <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                            View:
                            <div className="flex rounded-md border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] overflow-hidden">
                                {PANE_ORDER.map((pane) => (
                                    <button
                                        key={pane}
                                        type="button"
                                        onClick={() => togglePane(pane)}
                                        className={`px-3 py-1.5 text-sm font-medium transition ${
                                            visiblePanes[pane]
                                                ? 'bg-[var(--color-surface-panel)] text-[var(--color-accent)] shadow-sm'
                                                : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
                                        }`}
                                    >
                                        {pane === 'checklist' ? 'Checklist' : pane === 'summary' ? 'Summary' : 'Documents'}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
                {backError && (
                    <div className="w-full rounded border border-[var(--color-danger-soft)] bg-[var(--color-danger-soft)] px-3 py-2 text-xs text-[var(--color-text-danger)]">
                        {backError}
                    </div>
                )}
            </div>

            <div ref={workspaceRef} className="flex h-[calc(100vh-96px)] min-h-0 overflow-hidden bg-[var(--color-surface-panel-alt)]">
                {renderLayout()}
            </div>
        </div>
    );
};

const RunWorkspace = ({
    runId,
    title,
    initialCaseState,
    onBackToReview
}) => (
    <WorkspaceStateProvider
        runId={initialCaseState?.runId}
        initialCaseState={initialCaseState}
    >
        <RunWorkspaceLayout runId={runId} title={title} onBackToReview={onBackToReview} />
    </WorkspaceStateProvider>
);

export default RunWorkspace;
