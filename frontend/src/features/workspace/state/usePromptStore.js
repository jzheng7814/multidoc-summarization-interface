import { useCallback, useEffect, useState } from 'react';
import { fetchSummaryPrompt } from '../../../services/apiClient';

const STORAGE_KEY = 'legal_case_summary_prompt_v1';

const loadStoredPrompt = () => {
    if (typeof window === 'undefined') {
        return null;
    }
    try {
        const stored = window.localStorage.getItem(STORAGE_KEY);
        return stored && stored.length ? stored : null;
    } catch (error) {
        console.warn('Unable to access localStorage for prompt', error);
        return null;
    }
};

const saveStoredPrompt = (prompt) => {
    if (typeof window === 'undefined') {
        return;
    }
    try {
        window.localStorage.setItem(STORAGE_KEY, prompt);
    } catch (error) {
        console.warn('Unable to store prompt in localStorage', error);
    }
};

const clearStoredPrompt = () => {
    if (typeof window === 'undefined') {
        return;
    }
    try {
        window.localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
        console.warn('Unable to clear prompt from localStorage', error);
    }
};

const usePromptStore = ({ enabled = true } = {}) => {
    const storedPrompt = enabled ? loadStoredPrompt() : null;
    const [prompt, setPrompt] = useState(storedPrompt ?? '');
    const [defaultPrompt, setDefaultPrompt] = useState('');
    const [hasCustomPrompt, setHasCustomPrompt] = useState(Boolean(storedPrompt));
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!enabled) {
            setPrompt('');
            setDefaultPrompt('');
            setHasCustomPrompt(false);
            setError(null);
            setIsLoading(false);
            return () => {};
        }

        let isMounted = true;
        setIsLoading(true);
        setError(null);
        fetchSummaryPrompt()
            .then((response) => {
                if (!isMounted) {
                    return;
                }
                const fetched = response?.prompt ?? '';
                setDefaultPrompt(fetched);
                if (!hasCustomPrompt) {
                    setPrompt(fetched);
                }
            })
            .catch((err) => {
                if (!isMounted) {
                    return;
                }
                setError(err);
            })
            .finally(() => {
                if (isMounted) {
                    setIsLoading(false);
                }
            });
        return () => {
            isMounted = false;
        };
    }, [enabled, hasCustomPrompt]);

    const savePrompt = useCallback((nextPrompt) => {
        if (!enabled) {
            return;
        }
        const value = typeof nextPrompt === 'string' ? nextPrompt : '';
        setPrompt(value);
        setHasCustomPrompt(true);
        saveStoredPrompt(value);
    }, [enabled]);

    const clearCustomPrompt = useCallback(() => {
        if (!enabled) {
            return;
        }
        setHasCustomPrompt(false);
        clearStoredPrompt();
        setPrompt(defaultPrompt);
    }, [defaultPrompt, enabled]);

    const commitPrompt = useCallback((nextPrompt) => {
        if (!enabled) {
            return;
        }
        const value = typeof nextPrompt === 'string' ? nextPrompt : '';
        if (defaultPrompt && value === defaultPrompt) {
            clearCustomPrompt();
            return;
        }
        savePrompt(value);
    }, [clearCustomPrompt, defaultPrompt, enabled, savePrompt]);

    return {
        prompt,
        defaultPrompt,
        hasCustomPrompt,
        isLoading,
        error,
        savePrompt,
        clearCustomPrompt,
        commitPrompt
    };
};

export default usePromptStore;
