import React, { useState } from "react";
import { getApiErrorMessage, summarizeTranscript } from "../services/api";
import { LoadingIndicatorButton } from "./LoadingIndicatorButton";

interface SummarizationPanelProps {
  videoId: string;
  onError: (error: Error | null) => void;
}

const SummarizationPanel: React.FC<SummarizationPanelProps> = ({
  videoId,
  onError,
}) => {
  const [summary, setSummary] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSummarize = async () => {
    setIsLoading(true);
    setSummary(null);
    onError(null);

    try {
      const response = await summarizeTranscript(videoId);
      setSummary(response.summary);
    } catch (error) {
      onError(new Error(getApiErrorMessage(error, "Summarization failed")));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          📝 Transcript Summary
        </h3>
        <LoadingIndicatorButton
          isLoading={isLoading}
          buttonText="Generate Summary"
          onClick={handleSummarize}
          disabled={isLoading}
        />
      </div>

      {summary && (
        <div className="mt-4">
          <div className="bg-gray-50 dark:bg-gray-900 rounded-md p-4 border-l-4 border-indigo-500 dark:border-indigo-400">
            <h4 className="text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">Summary:</h4>
            <p className="text-gray-700 dark:text-gray-300 leading-relaxed">{summary}</p>
          </div>
        </div>
      )}

      {!summary && !isLoading && (
        <div className="mt-4 text-center text-gray-500 dark:text-gray-400">
          <p>
            Click "Generate Summary" to get an AI-powered summary of the entire
            transcript.
          </p>
        </div>
      )}
    </div>
  );
};

export default SummarizationPanel;
