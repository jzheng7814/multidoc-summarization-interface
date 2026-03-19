import React, { useEffect, useMemo, useState } from 'react';
import { useDocuments, useHighlight, useChecklist } from './state/WorkspaceProvider';
import { computeOverlayRects, createRangeFromOffsets } from '../../utils/selection';

const DocumentsPanel = ({ checklistReadOnly = false }) => {
    const {
        documents,
        selectedDocument,
        setSelectedDocument,
        isLoadingDocuments,
        documentRef,
        getCurrentDocument
    } = useDocuments();
    const {
        activeHighlight,
        highlightRects,
        selectedDocumentText,
        selectedDocumentRange
    } = useHighlight();
    const { highlightsByDocument } = useChecklist();
    const [categoryHighlights, setCategoryHighlights] = useState([]);
    const activeChecklistHighlights = useMemo(
        () => highlightsByDocument?.[selectedDocument] || [],
        [highlightsByDocument, selectedDocument]
    );
    const currentDocumentText = getCurrentDocument() || 'No document content';
    const selectionAvailable = Boolean(
        selectedDocumentText &&
        selectedDocumentRange &&
        selectedDocument != null
    );

    useEffect(() => {
        const container = documentRef.current;
        if (!container || !activeChecklistHighlights.length) {
            setCategoryHighlights([]);
            return undefined;
        }

        const updateRects = () => {
            const next = [];
            activeChecklistHighlights.forEach((entry) => {
                if (entry.startOffset == null || entry.endOffset == null) {
                    return;
                }
                const range = createRangeFromOffsets(container, entry.startOffset, entry.endOffset);
                if (!range) {
                    return;
                }
                next.push({
                    id: entry.id,
                    color: entry.color,
                    label: entry.label,
                    rects: computeOverlayRects(container, range)
                });
            });
            setCategoryHighlights(next);
        };

        updateRects();
        const handleScroll = () => requestAnimationFrame(updateRects);
        container.addEventListener('scroll', handleScroll);
        window.addEventListener('resize', handleScroll);
        return () => {
            container.removeEventListener('scroll', handleScroll);
            window.removeEventListener('resize', handleScroll);
        };
    }, [activeChecklistHighlights, documentRef, currentDocumentText]);

    return (
        <div className="flex-1 h-full min-h-0 min-w-0 bg-[var(--color-surface-panel)] flex flex-col border-l border-[var(--color-border)]">
            <div className="border-b border-[var(--color-border)] px-4 py-3">
                <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Document Viewer</h2>
                <p className="text-xs text-[var(--color-text-muted)]">Select spans to add checklist entries. Highlights show captured facts.</p>
            </div>

            <div className="flex-1 p-4 flex flex-col space-y-4 min-h-0 min-w-0 overflow-hidden">
                {documents.length > 0 ? (
                    <select
                        value={selectedDocument != null ? String(selectedDocument) : ''}
                        onChange={(event) => {
                            const nextValue = Number.parseInt(event.target.value, 10);
                            if (!Number.isNaN(nextValue)) {
                                setSelectedDocument(nextValue);
                            }
                        }}
                        className="w-full px-3 py-2 border border-[var(--color-input-border)] rounded-md bg-[var(--color-input-bg)] text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                    >
                        {documents.map((doc) => (
                            <option key={doc.id} value={String(doc.id)}>
                                {doc.title}
                                {doc.type ? ` (${doc.type})` : ''}
                            </option>
                        ))}
                    </select>
                ) : (
                    <div className="text-sm text-[var(--color-text-muted)]">
                        {isLoadingDocuments ? 'Loading documents...' : 'No documents loaded'}
                    </div>
                )}

                <div className="relative flex-1 min-h-0 min-w-0 overflow-hidden">
                    <div
                        ref={documentRef}
                        className="relative h-full w-full bg-[var(--color-surface-panel-alt)] border border-[var(--color-border)] rounded-md p-4 overflow-y-auto overflow-x-auto overscroll-contain cursor-text"
                    >
                        <pre className="text-xs leading-relaxed font-mono whitespace-pre-wrap break-words text-[var(--color-text-primary)] min-h-full w-full">
                            {currentDocumentText}
                        </pre>
                        {selectionAvailable && !checklistReadOnly && (
                            <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-[var(--color-overlay-scrim)] px-3 py-1 text-xs text-[var(--color-text-inverse)] shadow">
                                Select a checklist category to capture this span.
                            </div>
                        )}
                        {categoryHighlights.map((entry) =>
                            entry.rects.map((rect, index) => (
                                <span
                                    key={`${entry.id}-${index}`}
                                    className="pointer-events-none absolute rounded-sm border"
                                    style={{
                                        top: rect.top,
                                        left: rect.left,
                                        width: rect.width,
                                        height: rect.height,
                                        backgroundColor: entry.color,
                                        opacity: 0.15,
                                        zIndex: 5,
                                        borderColor: 'var(--color-surface-panel-ghost)'
                                    }}
                                />
                            ))
                        )}
                        {activeHighlight?.useOverlay && activeHighlight.type === 'document' && highlightRects.map((rect, index) => (
                            <span
                                key={`document-highlight-${index}`}
                                className="pointer-events-none absolute z-10 rounded-sm bg-[var(--color-surface-highlight-yellow)]"
                                style={{
                                    top: rect.top,
                                    left: rect.left,
                                    width: rect.width,
                                    height: rect.height
                                }}
                            />
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default DocumentsPanel;
