import React, { useCallback, useMemo, useState } from 'react';
import HomeScreen from './features/home/HomeScreen';
import SummaryWorkspace from './features/workspace/SummaryWorkspace';
import { uploadDocuments } from './services/apiClient';
import { normaliseImportedCaseState } from './features/workspace/caseState';

const App = () => {
    const [currentPage, setCurrentPage] = useState('home');
    const [intakeMode, setIntakeMode] = useState('caseId');
    const [caseId, setCaseId] = useState('');
    const [caseIdError, setCaseIdError] = useState('');
    const [uploadCaseName, setUploadCaseName] = useState('');
    const [uploadedDocuments, setUploadedDocuments] = useState([]);
    const [isUploading, setIsUploading] = useState(false);
    const [stateFile, setStateFile] = useState(null);
    const [isImportingState, setIsImportingState] = useState(false);
    const [initialCaseState, setInitialCaseState] = useState(null);
    const [activeCaseId, setActiveCaseId] = useState('');

    const handleProceed = useCallback(async () => {
        if (intakeMode === 'state') {
            if (!stateFile) {
                setCaseIdError('Please choose a saved case-state JSON file to continue.');
                return;
            }
            setIsImportingState(true);
            setCaseIdError('');
            try {
                const text = await stateFile.text();
                const parsedPayload = JSON.parse(text);
                const parsedState = normaliseImportedCaseState(parsedPayload);
                setInitialCaseState(parsedState);
                setCaseId(parsedState.caseId);
                setActiveCaseId(parsedState.caseId);
                setCurrentPage('summary');
            } catch (error) {
                setCaseIdError(error.message || 'Failed to import saved case state.');
            } finally {
                setIsImportingState(false);
            }
            return;
        }

        if (intakeMode === 'upload') {
            if (!uploadCaseName.trim()) {
                setCaseIdError('Please enter a case name to continue.');
                return;
            }
            if (!uploadedDocuments.length) {
                setCaseIdError('Please add at least one document to continue.');
                return;
            }
            setIsUploading(true);
            setCaseIdError('');
            try {
                const response = await uploadDocuments({
                    caseName: uploadCaseName,
                    documents: uploadedDocuments
                });
                const assignedCaseId = String(response?.caseId ?? response?.case_id ?? '').trim();
                if (!assignedCaseId) {
                    throw new Error('Upload succeeded but no case ID was returned.');
                }
                window.alert(`Assigned case ID: ${assignedCaseId}`);
                setInitialCaseState(null);
                setCaseId(assignedCaseId);
                setActiveCaseId(assignedCaseId);
                setCurrentPage('summary');
            } catch (error) {
                setCaseIdError(error.message || 'Failed to upload documents.');
            } finally {
                setIsUploading(false);
            }
            return;
        }

        const normalisedCaseId = (caseId || '').trim();
        if (!normalisedCaseId) {
            setCaseIdError('Please enter a valid case ID to continue.');
            return;
        }
        setCaseIdError('');
        setInitialCaseState(null);
        setActiveCaseId(normalisedCaseId);
        setCurrentPage('summary');
    }, [caseId, intakeMode, stateFile, uploadCaseName, uploadedDocuments]);

    const handleExitWorkspace = useCallback((error) => {
        setCurrentPage('home');
        setInitialCaseState(null);
        if (error) {
            setCaseIdError(error.message || 'Failed to load the requested case.');
        }
    }, []);

    const canProceed = useMemo(() => {
        if (intakeMode === 'state') {
            return !isImportingState && Boolean(stateFile);
        }
        if (intakeMode === 'upload') {
            return !isUploading && uploadCaseName.trim().length > 0 && uploadedDocuments.length > 0;
        }
        return caseId.trim().length > 0;
    }, [caseId, intakeMode, isImportingState, isUploading, stateFile, uploadCaseName, uploadedDocuments.length]);

    if (currentPage === 'home') {
        return (
            <HomeScreen
                intakeMode={intakeMode}
                onIntakeModeChange={(mode) => {
                    setIntakeMode(mode);
                    if (caseIdError) {
                        setCaseIdError('');
                    }
                }}
                caseId={caseId}
                caseIdError={caseIdError}
                onCaseIdChange={(value) => {
                    setCaseId(value);
                    if (caseIdError) {
                        setCaseIdError('');
                    }
                }}
                uploadCaseName={uploadCaseName}
                onUploadCaseNameChange={(value) => {
                    setUploadCaseName(value);
                    if (caseIdError) {
                        setCaseIdError('');
                    }
                }}
                uploadedDocuments={uploadedDocuments}
                onUploadedDocumentsChange={(documents) => {
                    setUploadedDocuments(documents);
                    if (caseIdError) {
                        setCaseIdError('');
                    }
                }}
                stateFile={stateFile}
                onStateFileChange={(file) => {
                    setStateFile(file);
                    if (caseIdError) {
                        setCaseIdError('');
                    }
                }}
                isUploading={isUploading}
                isImportingState={isImportingState}
                onProceed={handleProceed}
                canProceed={canProceed}
            />
        );
    }

    return (
        <SummaryWorkspace
            onExit={handleExitWorkspace}
            caseId={activeCaseId}
            initialCaseState={initialCaseState}
        />
    );
};

export default App;
