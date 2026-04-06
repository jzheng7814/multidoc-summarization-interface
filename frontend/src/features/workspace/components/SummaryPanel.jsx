import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Edit3, Plus } from 'lucide-react';
import { useSummary, useHighlight } from '../state/WorkspaceProvider';
import SummaryPatchPanel from './SummaryPatchPanel';
import { createRangeFromOffsets, computeOverlayRects, scrollRangeIntoView } from '../../../utils/selection';

const SummaryPanel = () => {
    const {
        summaryText,
        setSummaryText,
        isEditMode,
        toggleEditMode,
        summaryRef,
        versionHistory,
        activeVersionId,
        saveCurrentVersion,
        selectVersion,
        patchAction,
        activePatchId,
        clearPatchPreview
    } = useSummary();
    const {
        activeHighlight,
        highlightRects
    } = useHighlight();
    const [patchOverlayRects, setPatchOverlayRects] = useState([]);
    const [patchOverlayMeta, setPatchOverlayMeta] = useState(null);
    const patchPanelRef = useRef(null);

    useEffect(() => {
        if (isEditMode || (patchAction && patchAction.isStale)) {
            clearPatchPreview();
        }
    }, [isEditMode, patchAction, clearPatchPreview]);

    useEffect(() => {
        if (!activePatchId || !patchAction || patchAction.isStale || !summaryRef.current) {
            setPatchOverlayRects([]);
            setPatchOverlayMeta(null);
            return;
        }
        const target = patchAction.patches.find((patch) => patch.id === activePatchId && patch.status === 'applied');
        if (!target) {
            setPatchOverlayRects([]);
            setPatchOverlayMeta(null);
            return;
        }
        const container = summaryRef.current;
        const resolveEnd = () => {
            if (target.currentEnd > target.currentStart) {
                return target.currentEnd;
            }
            if (summaryText.length > target.currentStart) {
                return target.currentStart + 1;
            }
            return target.currentStart;
        };
        const highlightEnd = resolveEnd();

        const updateRects = () => {
            const range = createRangeFromOffsets(container, target.currentStart, highlightEnd);
            if (!range) {
                setPatchOverlayRects([]);
                return;
            }
            scrollRangeIntoView(container, range);
            setPatchOverlayRects(computeOverlayRects(container, range));
        };

        updateRects();
        setPatchOverlayMeta({ deletedText: target.deletedText, insertText: target.insertText });

        const handleScroll = () => requestAnimationFrame(updateRects);
        container.addEventListener('scroll', handleScroll);
        window.addEventListener('resize', handleScroll);
        return () => {
            container.removeEventListener('scroll', handleScroll);
            window.removeEventListener('resize', handleScroll);
        };
    }, [activePatchId, patchAction, summaryRef, summaryText.length]);

    useEffect(() => {
        if (typeof document === 'undefined') {
            return undefined;
        }
        if (!activePatchId) {
            return undefined;
        }
        const handleDocumentClick = (event) => {
            if (!summaryRef.current) {
                return;
            }
            if (summaryRef.current.contains(event.target)) {
                return;
            }
            if (patchPanelRef.current && patchPanelRef.current.contains(event.target)) {
                return;
            }
            clearPatchPreview();
        };
        document.addEventListener('mousedown', handleDocumentClick);
        return () => {
            document.removeEventListener('mousedown', handleDocumentClick);
        };
    }, [activePatchId, clearPatchPreview, summaryRef]);

    const handleVersionSelect = useCallback((event) => {
        selectVersion(event.target.value);
    }, [selectVersion]);

    const versionOptions = useMemo(() => versionHistory.map((entry) => {
        const date = entry.savedAt ? new Date(entry.savedAt) : null;
        const hasValidDate = date && !Number.isNaN(date.getTime());
        return {
            id: entry.id,
            label: hasValidDate ? date.toLocaleString() : entry.savedAt || entry.id
        };
    }), [versionHistory]);

    return (
        <div className="flex-1 h-full min-h-0 bg-[var(--color-surface-panel)] flex flex-col overflow-hidden border-l border-[var(--color-border)]">
            <div className="border-b border-[var(--color-border)] p-4 space-y-3 bg-[var(--color-surface-panel)]">
                <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">Summary</h2>
                    <div className="flex items-center space-x-2">
                        <button
                            onClick={toggleEditMode}
                            className={`flex items-center px-3 py-1 text-sm rounded transition ${
                                isEditMode
                                    ? 'bg-[var(--color-accent)] text-[var(--color-text-inverse)] hover:bg-[var(--color-accent-hover)]'
                                    : 'bg-[var(--color-surface-muted)] text-[var(--color-text-primary)] hover:bg-[var(--color-surface-muted-hover)]'
                            }`}
                        >
                            <Edit3 className="h-4 w-4 mr-1" />
                            {isEditMode ? 'Exit Edit' : 'Edit'}
                        </button>
                    </div>
                </div>
                <div className="flex items-center space-x-2">
                    <select
                        value={activeVersionId || ''}
                        onChange={handleVersionSelect}
                        className="flex-1 px-3 py-2 border border-[var(--color-input-border)] rounded-md text-sm bg-[var(--color-input-bg)] text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                    >
                        <option value="">Current Draft</option>
                        {versionOptions.map((version) => (
                            <option key={version.id} value={version.id}>
                                {version.label}
                            </option>
                        ))}
                    </select>
                    <button
                        onClick={saveCurrentVersion}
                        className="p-2 text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]"
                        title="Save current version"
                    >
                        <Plus className="h-4 w-4" />
                    </button>
                </div>
            </div>

            <SummaryPatchPanel panelRef={patchPanelRef} />

            <div className="flex-1 flex flex-col min-h-0">
                <div className="flex-1 p-4 flex flex-col min-h-0">
                    <div className="relative flex-1 min-h-0">
                        {isEditMode ? (
                            <textarea
                                ref={summaryRef}
                                value={summaryText}
                                onChange={(event) => setSummaryText(event.target.value)}
                                placeholder="Write your summary here..."
                                className="w-full h-full min-h-0 resize-none border border-[var(--color-input-border)] rounded-md px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] overflow-auto bg-[var(--color-input-bg)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)]"
                            />
                        ) : (
                            <div
                                ref={summaryRef}
                                className="relative h-full w-full border border-[var(--color-border)] rounded-md px-3 py-2 text-sm leading-relaxed cursor-text overflow-y-auto whitespace-pre-wrap bg-[var(--color-surface-panel)] text-[var(--color-text-primary)]"
                            >
                                {summaryText ? summaryText : (
                                    <span className="text-[var(--color-text-muted)]">Your summary will appear here...</span>
                                )}
                                {activeHighlight?.useOverlay && activeHighlight.type === 'summary' && highlightRects.map((rect, index) => (
                                    <span
                                        key={`summary-highlight-${index}`}
                                        className="pointer-events-none absolute z-10 rounded-sm bg-[var(--color-surface-highlight-yellow)]"
                                        style={{
                                            top: rect.top,
                                            left: rect.left,
                                            width: rect.width,
                                            height: rect.height
                                        }}
                                    />
                                ))}
                                {patchOverlayRects.map((rect, index) => (
                                    <span
                                        key={`patch-preview-${index}`}
                                        className="pointer-events-none absolute z-30 rounded-sm bg-[var(--color-surface-highlight-blue)]"
                                        style={{
                                            top: rect.top,
                                            left: rect.left,
                                            width: rect.width,
                                            height: rect.height
                                        }}
                                    />
                                ))}
                                {patchOverlayMeta?.deletedText && patchOverlayRects[0] && (
                                    <div
                                        className="pointer-events-none absolute z-40 rounded bg-[var(--color-surface-panel-ghost)] px-2 py-0.5 text-xs font-semibold text-[var(--color-danger)] line-through"
                                        style={{
                                            top: Math.max(0, patchOverlayRects[0].top - 20),
                                            left: patchOverlayRects[0].left
                                        }}
                                    >
                                        {patchOverlayMeta.deletedText || '(whitespace)'}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SummaryPanel;
