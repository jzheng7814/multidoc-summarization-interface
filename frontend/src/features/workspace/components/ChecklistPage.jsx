import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { useChecklist, useDocuments, useHighlight } from '../state/WorkspaceProvider';
import { buildDocumentLookup } from '../documentLookup';

const ChecklistPanel = ({ isActive, readOnly = false }) => {
    const { categories, addItem, deleteItem, updateItem } = useChecklist();
    const documents = useDocuments();
    const {
        selectedDocumentText,
        selectedDocumentRange,
        tooltipPosition,
        clearSelection,
        jumpToDocumentRange
    } = useHighlight();
    const [isPickerOpen, setIsPickerOpen] = useState(false);
    const [editingValueId, setEditingValueId] = useState('');
    const [editingValueInput, setEditingValueInput] = useState('');
    const [reselectingValueId, setReselectingValueId] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [actionError, setActionError] = useState(null);
    const [expandedEvidence, setExpandedEvidence] = useState(() => new Set());
    const [valueInput, setValueInput] = useState('');
    const [selectedCategoryId, setSelectedCategoryId] = useState('');
    const selectedDocumentRangeRef = useRef(selectedDocumentRange);
    const selectedDocumentIdRef = useRef(documents.selectedDocument);
    const reselectingValueIdRef = useRef(reselectingValueId);
    const reselectDragStartedRef = useRef(false);

    useEffect(() => {
        if (!selectedDocumentText) {
            setIsPickerOpen(false);
        }
    }, [selectedDocumentText]);

    useEffect(() => {
        if (readOnly && reselectingValueId) {
            setReselectingValueId('');
        }
    }, [readOnly, reselectingValueId]);

    useEffect(() => {
        selectedDocumentRangeRef.current = selectedDocumentRange;
    }, [selectedDocumentRange]);

    useEffect(() => {
        selectedDocumentIdRef.current = documents.selectedDocument;
    }, [documents.selectedDocument]);

    useEffect(() => {
        reselectingValueIdRef.current = reselectingValueId;
    }, [reselectingValueId]);

    const selectionAvailable = Boolean(
        !readOnly &&
        isActive &&
        selectedDocumentText &&
        selectedDocumentRange &&
        documents.selectedDocument != null
    );

    const handleDelete = useCallback(async (valueId) => {
        if (!valueId || readOnly) {
            return;
        }
        setActionError(null);
        try {
            await deleteItem(valueId);
        } catch (error) {
            setActionError(error.message || 'Failed to delete checklist item.');
        }
    }, [deleteItem, readOnly]);

    const valuesById = useMemo(() => {
        const lookup = {};
        categories.forEach((category) => {
            category.values.forEach((value) => {
                lookup[value.id] = value;
            });
        });
        return lookup;
    }, [categories]);

    useEffect(() => {
        if (reselectingValueId && !valuesById[reselectingValueId]) {
            setReselectingValueId('');
        }
    }, [reselectingValueId, valuesById]);

    const documentLookup = useMemo(() => buildDocumentLookup(documents.documents || []), [documents.documents]);

    useEffect(() => {
        if (isPickerOpen && categories.length > 0 && !selectedCategoryId) {
            setSelectedCategoryId(categories[0].id);
        }
    }, [categories, isPickerOpen, selectedCategoryId]);

    const resolveDocumentLabel = useCallback((documentId) => {
        if (documentId == null) {
            return 'No document reference';
        }
        if (documentId === -1) {
            return 'Summary';
        }
        const doc = documentLookup[documentId];
        if (doc) {
            return doc.title || doc.name || `Document ${documentId}`;
        }
        return `Document ${documentId}`;
    }, [documentLookup]);

    const extractEvidenceText = useCallback((value) => {
        const doc = documentLookup[value.documentId];
        if (
            !doc ||
            value.startOffset == null ||
            value.endOffset == null ||
            value.endOffset <= value.startOffset
        ) {
            return null;
        }
        const boundedStart = Math.max(0, Math.min(value.startOffset, doc.content.length));
        const boundedEnd = Math.max(boundedStart, Math.min(value.endOffset, doc.content.length));
        if (boundedEnd <= boundedStart) {
            return null;
        }
        return doc.content.slice(boundedStart, boundedEnd);
    }, [documentLookup]);

    const toggleEvidence = useCallback((valueId) => {
        setExpandedEvidence((current) => {
            const next = new Set(current);
            if (next.has(valueId)) {
                next.delete(valueId);
            } else {
                next.add(valueId);
            }
            return next;
        });
    }, []);

    const handleValueNavigate = useCallback((value) => {
        if (
            value.documentId == null ||
            value.startOffset == null ||
            value.endOffset == null ||
            value.endOffset <= value.startOffset
        ) {
            return;
        }
        jumpToDocumentRange({
            documentId: value.documentId,
            range: { start: value.startOffset, end: value.endOffset }
        });
    }, [jumpToDocumentRange]);

    const handleOpenModal = useCallback(() => {
        if (readOnly) {
            return;
        }
        setActionError(null);
        setValueInput('');
        if (categories.length > 0) {
            setSelectedCategoryId(categories[0].id);
        }
        setIsPickerOpen(true);
    }, [categories, readOnly]);

    const handleOpenEditValue = useCallback((value) => {
        if (readOnly || !value?.id) {
            return;
        }
        setActionError(null);
        setEditingValueId(value.id);
        setEditingValueInput(String(value.text || value.value || ''));
    }, [readOnly]);

    const handleCloseEditValue = useCallback(() => {
        setEditingValueId('');
        setEditingValueInput('');
        setIsSubmitting(false);
    }, []);

    const handleSubmitEditValue = useCallback(async () => {
        if (!editingValueId) {
            return;
        }
        const trimmed = editingValueInput.trim();
        if (!trimmed) {
            setActionError('Checklist text is required.');
            return;
        }
        setIsSubmitting(true);
        setActionError(null);
        try {
            await updateItem(editingValueId, (current) => ({
                ...current,
                value: trimmed,
                text: trimmed
            }));
            handleCloseEditValue();
        } catch (error) {
            setActionError(error.message || 'Failed to update checklist item.');
        } finally {
            setIsSubmitting(false);
        }
    }, [editingValueId, editingValueInput, handleCloseEditValue, updateItem]);

    const handleStartReselectSpan = useCallback((value) => {
        if (readOnly || !value?.id) {
            return;
        }
        setActionError(null);
        clearSelection();
        window.getSelection()?.removeAllRanges();
        setReselectingValueId(value.id);
        if (
            value.documentId != null &&
            value.startOffset != null &&
            value.endOffset != null &&
            value.endOffset > value.startOffset
        ) {
            jumpToDocumentRange({
                documentId: value.documentId,
                range: { start: value.startOffset, end: value.endOffset }
            });
        }
    }, [clearSelection, jumpToDocumentRange, readOnly]);

    const handleCancelReselectSpan = useCallback(() => {
        setReselectingValueId('');
        clearSelection();
        window.getSelection()?.removeAllRanges();
    }, [clearSelection]);

    const handleCloseModal = useCallback(() => {
        setIsPickerOpen(false);
        setIsSubmitting(false);
        setValueInput('');
    }, []);

    const handleSubmit = useCallback(async () => {
        if (!selectionAvailable) {
            setActionError('Select text in a document to add a checklist item.');
            return;
        }
        const trimmed = valueInput.trim();
        if (!trimmed) {
            setActionError('Checklist text is required.');
            return;
        }
        if (!selectedCategoryId) {
            setActionError('Select a checklist category.');
            return;
        }
        setIsSubmitting(true);
        setActionError(null);
        try {
            await addItem({
                categoryId: selectedCategoryId,
                text: trimmed,
                documentId: documents.selectedDocument,
                startOffset: selectedDocumentRange.start,
                endOffset: selectedDocumentRange.end
            });
            clearSelection();
            setIsPickerOpen(false);
            setValueInput('');
        } catch (error) {
            setActionError(error.message || 'Failed to add checklist item.');
        } finally {
            setIsSubmitting(false);
        }
    }, [addItem, clearSelection, documents.selectedDocument, selectedCategoryId, selectedDocumentRange, selectionAvailable, valueInput]);

    useEffect(() => {
        if (!reselectingValueId || readOnly) {
            return undefined;
        }
        const container = documents.documentRef.current;
        if (!container) {
            return undefined;
        }

        const handleMouseDown = (event) => {
            if (!container.contains(event.target)) {
                return;
            }
            reselectDragStartedRef.current = true;
            setActionError(null);
        };

        const handleMouseUp = () => {
            if (!reselectDragStartedRef.current) {
                return;
            }
            reselectDragStartedRef.current = false;

            window.requestAnimationFrame(() => {
                const activeValueId = reselectingValueIdRef.current;
                if (!activeValueId) {
                    return;
                }
                const value = valuesById[activeValueId];
                if (!value) {
                    setReselectingValueId('');
                    return;
                }

                const selectedRange = selectedDocumentRangeRef.current;
                const selectedDocumentId = selectedDocumentIdRef.current;
                if (
                    !selectedRange ||
                    selectedDocumentId == null ||
                    selectedRange.start == null ||
                    selectedRange.end == null ||
                    selectedRange.end <= selectedRange.start
                ) {
                    return;
                }

                void updateItem(activeValueId, (current) => ({
                    ...current,
                    documentId: selectedDocumentId,
                    startOffset: selectedRange.start,
                    endOffset: selectedRange.end
                })).then(() => {
                    setReselectingValueId('');
                    clearSelection();
                    window.getSelection()?.removeAllRanges();
                }).catch((error) => {
                    setActionError(error.message || 'Failed to update supporting span.');
                });
            });
        };

        container.addEventListener('mousedown', handleMouseDown);
        window.addEventListener('mouseup', handleMouseUp);
        return () => {
            container.removeEventListener('mousedown', handleMouseDown);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [clearSelection, documents.documentRef, readOnly, reselectingValueId, updateItem, valuesById]);

    const renderSelectionTooltip = () => {
        if (readOnly || !selectionAvailable || isPickerOpen || reselectingValueId) {
            return null;
        }
        const style = {
            left: tooltipPosition.x,
            top: tooltipPosition.y
        };
        return (
            <button
                type="button"
                data-preserve-selection="true"
                className="fixed z-50 -translate-x-1/2 rounded-full bg-[var(--color-accent)] px-3 py-1 text-xs font-semibold text-[var(--color-text-inverse)] shadow-lg hover:bg-[var(--color-accent-hover)]"
                style={style}
                onClick={handleOpenModal}
                onMouseDown={(event) => event.preventDefault()}
            >
                + Add item
            </button>
        );
    };

    const sortedCategories = useMemo(() => categories, [categories]);
    const isChecklistReady = sortedCategories.length > 0;

    return (
        <div className="h-full flex flex-col overflow-hidden bg-[var(--color-surface-panel)] border-r border-[var(--color-border)]">
            <div className="border-b border-[var(--color-border)] px-4 py-3">
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Document Checklist</h2>
                        <p className="text-xs text-[var(--color-text-muted)]">
                            {readOnly
                                ? 'Review extracted items and evidence spans.'
                                : 'Review extracted items or add your own from document spans.'}
                        </p>
                    </div>
                </div>
                <p className="mt-2 text-[11px] text-[var(--color-text-secondary)]">
                    {readOnly
                        ? 'Checklist is read-only for this stage.'
                        : 'Refine this checklist from document spans; generation pulls directly from here.'}
                </p>
                {!readOnly && reselectingValueId && (
                    <div className="mt-2 flex items-center justify-between gap-2 rounded border border-[var(--color-accent-soft)] bg-[var(--color-accent-soft)] px-2 py-1 text-[11px] text-[var(--color-text-secondary)]">
                        <span>Select a new span in the document viewer; it will save automatically.</span>
                        <button
                            type="button"
                            onClick={handleCancelReselectSpan}
                            className="text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]"
                        >
                            Cancel
                        </button>
                    </div>
                )}
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-[var(--color-surface-panel-alt)]">
                {!isChecklistReady ? (
                    <div className="text-xs text-[var(--color-text-muted)]">No checklist items yet.</div>
                ) : (
                    sortedCategories.map((category) => (
                        <div
                            key={category.id}
                            className="rounded-lg border bg-[var(--color-surface-panel)] shadow-sm"
                            style={{ borderColor: `${category.color}33` }}
                        >
                            <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
                                <div className="flex items-center gap-2">
                                    <span
                                        className="h-2.5 w-2.5 rounded-full"
                                        style={{ backgroundColor: category.color }}
                                    />
                                    <p className="text-sm font-semibold text-[var(--color-text-primary)]">{category.label}</p>
                                </div>
                                <span className="text-xs text-[var(--color-text-muted)]">{category.values.length} entries</span>
                            </div>
                            <div className="p-3 space-y-3">
                                {category.values.length === 0 ? (
                                    <p className="text-xs text-[var(--color-text-muted)]">Nothing captured yet.</p>
                                ) : (
                                    category.values.map((value) => (
                                        <div
                                            key={value.id}
                                            className="rounded border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] px-2 py-2"
                                        >
                                            {(() => {
                                                const evidenceText = extractEvidenceText(value);
                                                const canJump =
                                                    value.documentId != null &&
                                                    value.startOffset != null &&
                                                    value.endOffset != null &&
                                                    value.endOffset > value.startOffset;
                                                const isExpanded = expandedEvidence.has(value.id);
                                                const documentLabel = resolveDocumentLabel(value.documentId);
                                                return (
                                                    <>
                                                        <div className="flex items-start justify-between gap-3">
                                                            <div className="flex-1">
                                                                <p className="text-sm text-[var(--color-text-primary)]">
                                                                    {value.text || value.value || '—'}
                                                                </p>
                                                                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-text-muted)]">
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => canJump && handleValueNavigate(value)}
                                                                        disabled={!canJump}
                                                                        className={`text-left underline decoration-dotted ${
                                                                            canJump
                                                                                ? 'text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]'
                                                                                : 'cursor-not-allowed'
                                                                        }`}
                                                                    >
                                                                        {documentLabel}
                                                                    </button>
                                                                    {evidenceText ? (
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => toggleEvidence(value.id)}
                                                                            className="rounded border border-[var(--color-border)] bg-[var(--color-surface-panel)] px-2 py-1 text-[11px] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]"
                                                                        >
                                                                            {isExpanded ? 'Hide evidence' : 'Show evidence'}
                                                                        </button>
                                                                    ) : (
                                                                        <span className="text-[11px] text-[var(--color-text-muted)]">
                                                                            Evidence text unavailable
                                                                        </span>
                                                                    )}
                                                                </div>
                                                            </div>
                                                            {!readOnly && (
                                                                <div className="flex items-center gap-1">
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => handleOpenEditValue(value)}
                                                                        className="rounded border border-[var(--color-border)] bg-[var(--color-surface-panel)] px-2 py-1 text-[11px] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]"
                                                                    >
                                                                        Edit Value
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => handleStartReselectSpan(value)}
                                                                        className={`rounded border px-2 py-1 text-[11px] ${
                                                                            reselectingValueId === value.id
                                                                                ? 'border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]'
                                                                                : 'border-[var(--color-border)] bg-[var(--color-surface-panel)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]'
                                                                        }`}
                                                                    >
                                                                        Reselect Span
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => handleDelete(value.id)}
                                                                        className="text-[var(--color-text-muted)] hover:text-[var(--color-danger)]"
                                                                        title="Delete item"
                                                                    >
                                                                        <Trash2 className="h-4 w-4" />
                                                                    </button>
                                                                </div>
                                                            )}
                                                        </div>
                                                        {isExpanded && evidenceText && (
                                                            <div className="mt-2 rounded border border-[var(--color-border)] bg-[var(--color-surface-panel)] p-2 text-xs text-[var(--color-text-primary)]">
                                                                <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
                                                                    {evidenceText}
                                                                </pre>
                                                            </div>
                                                        )}
                                                    </>
                                                );
                                            })()}
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    ))
                )}
                {actionError && (
                    <div className="rounded bg-[var(--color-danger-soft)] px-3 py-2 text-xs text-[var(--color-danger)]">
                        {actionError}
                    </div>
                )}
                {!readOnly && isPickerOpen && selectionAvailable && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--color-overlay-scrim)] px-4">
                        <div
                            className="w-full max-w-xl rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-panel)] shadow-2xl"
                            data-preserve-selection="true"
                        >
                            <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
                                <div>
                                    <p className="text-sm font-semibold text-[var(--color-text-primary)]">Add checklist item</p>
                                    <p className="text-[11px] text-[var(--color-text-muted)]">Review the highlighted span and add your value.</p>
                                </div>
                                <button
                                    type="button"
                                    onClick={handleCloseModal}
                                    className="text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
                                    disabled={isSubmitting}
                                >
                                    Close
                                </button>
                            </div>
                            <div className="px-4 py-3 space-y-3">
                                <div>
                                    <p className="text-xs font-semibold text-[var(--color-text-secondary)] mb-1">Selected text</p>
                                    <div className="max-h-32 overflow-y-auto rounded border border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] p-2 text-xs text-[var(--color-text-primary)]">
                                        <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
                                            {selectedDocumentText}
                                        </pre>
                                    </div>
                                </div>
                                <div>
                                    <label className="text-xs font-semibold text-[var(--color-text-secondary)] mb-1 block" htmlFor="checklist-category">
                                        Checklist category
                                    </label>
                                    <select
                                        id="checklist-category"
                                        value={selectedCategoryId}
                                        onChange={(event) => setSelectedCategoryId(event.target.value)}
                                        className="w-full rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                        disabled={isSubmitting}
                                    >
                                        {sortedCategories.map((category) => (
                                            <option key={category.id} value={category.id}>
                                                {category.label}
                                            </option>
                                        ))}
                                    </select>
                                </div>
                                <div>
                                    <label className="text-xs font-semibold text-[var(--color-text-secondary)] mb-1 block" htmlFor="checklist-value">
                                        Checklist value
                                    </label>
                                    <textarea
                                        id="checklist-value"
                                        value={valueInput}
                                        onChange={(event) => setValueInput(event.target.value)}
                                        className="w-full min-h-[100px] rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                        placeholder="Describe the item in your own words…"
                                        disabled={isSubmitting}
                                    />
                                </div>
                            </div>
                            <div className="flex items-center justify-end gap-2 border-t border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] px-4 py-3">
                                <button
                                    type="button"
                                    onClick={handleCloseModal}
                                    className="rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)] disabled:opacity-50"
                                    disabled={isSubmitting}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="button"
                                    onClick={handleSubmit}
                                    className="rounded bg-[var(--color-accent)] px-3 py-1.5 text-sm font-semibold text-[var(--color-text-inverse)] shadow hover:bg-[var(--color-accent-hover)] disabled:opacity-60"
                                    disabled={isSubmitting}
                                >
                                    {isSubmitting ? 'Saving…' : 'Save to checklist'}
                                </button>
                            </div>
                        </div>
                    </div>
                )}
                {!readOnly && editingValueId && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--color-overlay-scrim)] px-4">
                        <div
                            className="w-full max-w-xl rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-panel)] shadow-2xl"
                            data-preserve-selection="true"
                        >
                            <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
                                <div>
                                    <p className="text-sm font-semibold text-[var(--color-text-primary)]">Edit checklist value</p>
                                    <p className="text-[11px] text-[var(--color-text-muted)]">Update the extracted value text.</p>
                                </div>
                                <button
                                    type="button"
                                    onClick={handleCloseEditValue}
                                    className="text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
                                    disabled={isSubmitting}
                                >
                                    Close
                                </button>
                            </div>
                            <div className="px-4 py-3 space-y-3">
                                <div>
                                    <label className="text-xs font-semibold text-[var(--color-text-secondary)] mb-1 block" htmlFor="edit-checklist-value">
                                        Checklist value
                                    </label>
                                    <textarea
                                        id="edit-checklist-value"
                                        value={editingValueInput}
                                        onChange={(event) => setEditingValueInput(event.target.value)}
                                        className="w-full min-h-[120px] rounded border border-[var(--color-input-border)] bg-[var(--color-input-bg)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                                        disabled={isSubmitting}
                                    />
                                </div>
                            </div>
                            <div className="flex items-center justify-end gap-2 border-t border-[var(--color-border)] bg-[var(--color-surface-panel-alt)] px-4 py-3">
                                <button
                                    type="button"
                                    onClick={handleCloseEditValue}
                                    className="rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)] disabled:opacity-50"
                                    disabled={isSubmitting}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="button"
                                    onClick={handleSubmitEditValue}
                                    className="rounded bg-[var(--color-accent)] px-3 py-1.5 text-sm font-semibold text-[var(--color-text-inverse)] shadow hover:bg-[var(--color-accent-hover)] disabled:opacity-60"
                                    disabled={isSubmitting}
                                >
                                    {isSubmitting ? 'Saving…' : 'Save value'}
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>
            {renderSelectionTooltip()}
        </div>
    );
};

export default ChecklistPanel;
