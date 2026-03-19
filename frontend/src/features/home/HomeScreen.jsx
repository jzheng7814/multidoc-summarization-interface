import React, { useState } from 'react';

const HomeScreen = ({ onStartNewRun }) => {
    const [isCreating, setIsCreating] = useState(false);
    const [error, setError] = useState('');

    const handleStart = async () => {
        if (!onStartNewRun || isCreating) {
            return;
        }
        setError('');
        setIsCreating(true);
        try {
            await onStartNewRun();
        } catch (createError) {
            setError(createError?.message || 'Failed to create a new run.');
            setIsCreating(false);
        }
    };

    return (
        <div className="min-h-screen bg-[var(--color-surface-app)] text-[var(--color-text-primary)] flex items-center justify-center p-6">
            <div className="w-full max-w-xl rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-panel)] shadow-lg p-8 space-y-4">
                <button
                    type="button"
                    onClick={handleStart}
                    disabled={isCreating}
                    className="w-full rounded bg-[var(--color-accent)] px-4 py-3 text-sm font-semibold text-[var(--color-text-inverse)] hover:bg-[var(--color-accent-hover)] disabled:opacity-60"
                >
                    {isCreating ? 'Creating Run…' : 'Start New Summary Generation Run'}
                </button>
                {error && (
                    <div className="rounded border border-[var(--color-danger-soft)] bg-[var(--color-danger-soft)] px-3 py-2 text-xs text-[var(--color-text-danger)]">
                        {error}
                    </div>
                )}
            </div>
        </div>
    );
};

export default HomeScreen;
