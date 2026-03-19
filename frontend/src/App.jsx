import React, { useCallback, useEffect, useMemo, useState } from 'react';

import HomeScreen from './features/home/HomeScreen';
import RunFlowPage from './features/runFlow/RunFlowPage';
import { createRun } from './services/apiClient';

function parseRunIdFromPath(pathname) {
    const match = String(pathname || '').match(/^\/run\/([^/]+)\/?$/);
    if (!match) {
        return null;
    }
    const rawRunId = decodeURIComponent(match[1] || '').trim();
    return rawRunId || null;
}

const App = () => {
    const [pathname, setPathname] = useState(() => window.location.pathname || '/');

    useEffect(() => {
        const handlePopState = () => {
            setPathname(window.location.pathname || '/');
        };
        window.addEventListener('popstate', handlePopState);
        return () => window.removeEventListener('popstate', handlePopState);
    }, []);

    const navigate = useCallback((nextPath, { replace = false } = {}) => {
        const target = nextPath || '/';
        if (replace) {
            window.history.replaceState({}, '', target);
        } else {
            window.history.pushState({}, '', target);
        }
        setPathname(target);
    }, []);

    const runId = useMemo(() => parseRunIdFromPath(pathname), [pathname]);

    const handleStartNewRun = useCallback(async () => {
        const payload = await createRun();
        const newRunId = String(payload?.runId ?? payload?.run_id ?? '').trim();
        if (!newRunId) {
            throw new Error('Backend did not return a run ID.');
        }
        navigate(`/run/${encodeURIComponent(newRunId)}`);
    }, [navigate]);

    if (pathname === '/') {
        return <HomeScreen onStartNewRun={handleStartNewRun} />;
    }

    if (runId) {
        return <RunFlowPage runId={runId} />;
    }

    return <HomeScreen onStartNewRun={handleStartNewRun} />;
};

export default App;
