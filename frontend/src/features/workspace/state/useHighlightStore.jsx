import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    supportsCssHighlight,
    computeOverlayRects,
    getOffsetsForRange,
    createRangeFromOffsets,
    scrollRangeIntoView
} from '../../../utils/selection';

const CSS_HIGHLIGHT_KEY = 'jump-highlight';
const EMPTY_TOOLTIP_POSITION = { x: 0, y: 0 };

const useHighlightStore = ({ summary, documents }) => {
    const [selectedText, setSelectedText] = useState('');
    const [selectedRange, setSelectedRange] = useState(null);
    const [selectedDocumentText, setSelectedDocumentText] = useState('');
    const [selectedDocumentRange, setSelectedDocumentRange] = useState(null);
    const [tooltipPosition, setTooltipPosition] = useState(EMPTY_TOOLTIP_POSITION);
    const [pendingHighlight, setPendingHighlight] = useState(null);
    const [pendingScroll, setPendingScroll] = useState(null);
    const [activeHighlight, setActiveHighlight] = useState(null);
    const [highlightRects, setHighlightRects] = useState([]);
    const cssHighlightHandleRef = useRef(null);
    const [interactionMode, setInteractionModeState] = useState('canvas');

    const setInteractionMode = useCallback((mode) => {
        setInteractionModeState(mode === 'checklist' ? 'checklist' : 'canvas');
    }, []);

    const clearCssHighlight = useCallback(() => {
        if (!supportsCssHighlight()) {
            return;
        }
        if (cssHighlightHandleRef.current) {
            window.CSS.highlights.delete(cssHighlightHandleRef.current);
            cssHighlightHandleRef.current = null;
        }
    }, []);

    const applyCssHighlight = useCallback((range) => {
        if (!supportsCssHighlight()) {
            return false;
        }
        clearCssHighlight();
        const highlight = new window.Highlight(range);
        window.CSS.highlights.set(CSS_HIGHLIGHT_KEY, highlight);
        cssHighlightHandleRef.current = CSS_HIGHLIGHT_KEY;
        return true;
    }, [clearCssHighlight]);

    const clearActiveHighlight = useCallback(() => {
        clearCssHighlight();
        setActiveHighlight(null);
        setHighlightRects([]);
    }, [clearCssHighlight]);

    useEffect(() => () => clearCssHighlight(), [clearCssHighlight]);
    useEffect(() => {
        if (typeof document === 'undefined') {
            return;
        }
        if (!document.getElementById('workspace-highlight-style')) {
            const styleEl = document.createElement('style');
            styleEl.id = 'workspace-highlight-style';
            styleEl.textContent = '::highlight(' + CSS_HIGHLIGHT_KEY + ') { background-color: rgba(250, 204, 21, 0.08); color: var(--color-text-primary); }';
            document.head.appendChild(styleEl);
        }
    }, []);

    const resetSelectionState = useCallback(() => {
        setSelectedText('');
        setSelectedRange(null);
        setSelectedDocumentText('');
        setSelectedDocumentRange(null);
        setTooltipPosition(EMPTY_TOOLTIP_POSITION);
    }, []);

    const updateTooltip = useCallback((rect) => {
        setTooltipPosition({
            x: rect.left + rect.width / 2,
            y: rect.top - 30
        });
    }, []);

    const captureSummarySelection = useCallback((range, container) => {
        const offsets = getOffsetsForRange(container, range);
        if (!offsets) {
            return;
        }
        setSelectedText(offsets.text);
        setSelectedRange({ start: offsets.start, end: offsets.end });
        setSelectedDocumentText('');
        setSelectedDocumentRange(null);
        updateTooltip(range.getBoundingClientRect());
    }, [updateTooltip]);

    const captureDocumentSelection = useCallback((range, container) => {
        const offsets = getOffsetsForRange(container, range);
        if (!offsets) {
            return;
        }
        setSelectedDocumentText(offsets.text);
        setSelectedDocumentRange({ start: offsets.start, end: offsets.end });
        setSelectedText('');
        setSelectedRange(null);
        updateTooltip(range.getBoundingClientRect());
    }, [updateTooltip]);

    useEffect(() => {
        const handleSelectionChange = () => {
            const summaryEl = summary.summaryRef.current;
            const documentEl = documents.documentRef.current;

            if (!summaryEl && !documentEl) {
                return;
            }

            if (summaryEl instanceof HTMLTextAreaElement && document.activeElement === summaryEl) {
                const { selectionStart, selectionEnd, value } = summaryEl;
                if (selectionStart != null && selectionEnd != null && selectionStart !== selectionEnd) {
                    setSelectedText(value.slice(selectionStart, selectionEnd));
                    setSelectedRange({ start: selectionStart, end: selectionEnd });
                    setSelectedDocumentText('');
                    setSelectedDocumentRange(null);
                    const rect = summaryEl.getBoundingClientRect();
                    setTooltipPosition({ x: rect.left + rect.width / 2, y: rect.top - 30 });
                    return;
                }
            }

            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0) {
                return;
            }

            const range = selection.getRangeAt(0);

            if (summary.summaryRef.current && summary.summaryRef.current.contains(range.startContainer)) {
                if (!range.collapsed) {
                    captureSummarySelection(range, summary.summaryRef.current);
                } else {
                    resetSelectionState();
                }
                return;
            }

            if (documents.documentRef.current && documents.documentRef.current.contains(range.startContainer)) {
                if (!range.collapsed) {
                    captureDocumentSelection(range, documents.documentRef.current);
                } else {
                    resetSelectionState();
                }
                return;
            }

            resetSelectionState();
        };

        const handleClick = (event) => {
            if (event.target?.closest?.('[data-preserve-selection="true"]')) {
                return;
            }
            const summaryEl = summary.summaryRef.current;
            const documentEl = documents.documentRef.current;
            if (
                summaryEl && !summaryEl.contains(event.target) &&
                documentEl && !documentEl.contains(event.target)
            ) {
                resetSelectionState();
                window.getSelection()?.removeAllRanges();
                clearActiveHighlight();
            }
        };

        document.addEventListener('selectionchange', handleSelectionChange);
        document.addEventListener('click', handleClick);
        return () => {
            document.removeEventListener('selectionchange', handleSelectionChange);
            document.removeEventListener('click', handleClick);
        };
    }, [captureDocumentSelection, captureSummarySelection, clearActiveHighlight, documents.documentRef, documents.selectedDocument, interactionMode, resetSelectionState, summary.summaryRef]);

    useEffect(() => {
        const handleKeyDown = (event) => {
            if (event.key === 'Escape' && (selectedText || selectedDocumentText)) {
                event.preventDefault();
                window.getSelection()?.removeAllRanges();
                resetSelectionState();
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [resetSelectionState, selectedDocumentText, selectedText]);

    useEffect(() => {
        if (summary.isEditMode) {
            clearActiveHighlight();
        }
    }, [summary.isEditMode, clearActiveHighlight]);

    useEffect(() => {
        if (activeHighlight?.type === 'document' && activeHighlight.documentId && activeHighlight.documentId !== documents.selectedDocument) {
            clearActiveHighlight();
        }
    }, [activeHighlight, clearActiveHighlight, documents.selectedDocument]);

    const renderSummaryWithSuggestions = useCallback((text) => text, []);

    const jumpToDocumentRange = useCallback(({ documentId, range }) => {
        if (!range || range.start == null || range.end == null || range.start === range.end) {
            return;
        }
        const targetDocumentId = documentId ?? documents.selectedDocument;
        const performScroll = () => {
            const container = documents.documentRef.current;
            if (!container) {
                return;
            }
            const domRange = createRangeFromOffsets(container, range.start, range.end);
            if (domRange) {
                scrollRangeIntoView(container, domRange);
            }
        };

        if (
            targetDocumentId != null &&
            targetDocumentId !== documents.selectedDocument &&
            documents.documents.some((doc) => doc.id === targetDocumentId)
        ) {
            setPendingScroll({ documentId: targetDocumentId, range });
            documents.setSelectedDocument(targetDocumentId);
            return;
        }

        if (targetDocumentId == null) {
            return;
        }

        performScroll();
    }, [documents]);

    useEffect(() => {
        if (!pendingHighlight) {
            return;
        }

        const { type, range, documentId } = pendingHighlight;
        if (!range || range.start == null || range.end == null || range.start === range.end) {
            setPendingHighlight(null);
            return;
        }

        if (type === 'summary' && summary.isEditMode) {
            setPendingHighlight(null);
            return;
        }

        if (type === 'document' && documentId != null && documentId !== documents.selectedDocument) {
            return;
        }

        const container = type === 'document' ? documents.documentRef.current : summary.summaryRef.current;
        if (!container) {
            return;
        }

        const applyHighlight = () => {
            const domRange = createRangeFromOffsets(container, range.start, range.end);
            if (!domRange) {
                clearActiveHighlight();
                setPendingHighlight(null);
                return;
            }

            scrollRangeIntoView(container, domRange);
            const usedCss = applyCssHighlight(domRange);
            if (!usedCss) {
                setHighlightRects(computeOverlayRects(container, domRange));
            } else {
                setHighlightRects([]);
            }

            setActiveHighlight({
                type,
                documentId: type === 'document' ? documentId || documents.selectedDocument : null,
                range: { start: range.start, end: range.end },
                useOverlay: !usedCss
            });
            setPendingHighlight(null);
        };

        requestAnimationFrame(applyHighlight);
    }, [applyCssHighlight, clearActiveHighlight, documents.documentRef, documents.selectedDocument, pendingHighlight, summary.isEditMode, summary.summaryRef]);

    useEffect(() => {
        if (!pendingScroll) {
            return;
        }
        if (
            pendingScroll.documentId != null &&
            pendingScroll.documentId !== documents.selectedDocument
        ) {
            return;
        }
        const container = documents.documentRef.current;
        if (!container) {
            return;
        }
        const domRange = createRangeFromOffsets(container, pendingScroll.range.start, pendingScroll.range.end);
        if (domRange) {
            scrollRangeIntoView(container, domRange);
        }
        setPendingScroll(null);
    }, [documents.documentRef, documents.selectedDocument, pendingScroll]);

    useEffect(() => {
        if (!activeHighlight || !activeHighlight.useOverlay) {
            return;
        }

        const container = activeHighlight.type === 'document' ? documents.documentRef.current : summary.summaryRef.current;
        if (!container) {
            return;
        }

        let animationFrameId = null;

        const updateRects = () => {
            const overlayRange = createRangeFromOffsets(container, activeHighlight.range.start, activeHighlight.range.end);
            if (!overlayRange) {
                clearActiveHighlight();
                return;
            }
            setHighlightRects(computeOverlayRects(container, overlayRange));
        };

        updateRects();

        const handleScrollOrResize = () => {
            if (animationFrameId) {
                cancelAnimationFrame(animationFrameId);
            }
            animationFrameId = requestAnimationFrame(updateRects);
        };

        container.addEventListener('scroll', handleScrollOrResize);
        window.addEventListener('resize', handleScrollOrResize);

        return () => {
            container.removeEventListener('scroll', handleScrollOrResize);
            window.removeEventListener('resize', handleScrollOrResize);
            if (animationFrameId) {
                cancelAnimationFrame(animationFrameId);
            }
        };
    }, [activeHighlight, clearActiveHighlight, documents.documentRef, summary.summaryRef]);

    const value = useMemo(() => ({
        selectedText,
        selectedRange,
        selectedDocumentText,
        selectedDocumentRange,
        tooltipPosition,
        activeHighlight,
        highlightRects,
        renderSummaryWithSuggestions,
        jumpToDocumentRange,
        clearActiveHighlight,
        setInteractionMode,
        interactionMode,
        clearSelection: resetSelectionState
    }), [
        activeHighlight,
        jumpToDocumentRange,
        highlightRects,
        renderSummaryWithSuggestions,
        selectedDocumentRange,
        selectedDocumentText,
        selectedRange,
        selectedText,
        tooltipPosition,
        clearActiveHighlight,
        interactionMode,
        setInteractionMode,
        resetSelectionState
    ]);

    return value;
};

export default useHighlightStore;
