import axios from "axios";

import type {
  TranscriptionRequest,
  TranscriptionResponse,
  WhisperModelType,
} from "../types/transcription.types";
import type {
  QuestionRequest,
  QuestionResponse,
  SearchType,
} from "../types/search.types";

import type {
  LlmInfo,
  LlmListResponse,
  LlmSelectResponse,
} from "../types/llms.types";

import type {
  SummarizationRequest,
  SummarizationResponse,
} from "../types/summarization.types";

import type {
  AddVideoResponse,
  AddVideosResponse,
  ProcessingStatusResponse,
  VideoGroupsResponse,
  VideoLibraryResponse,
  VideoTranscriptResponse,
} from "../types/library.types";

export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:9091";
const API_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS ?? "30000");
const API_READ_RETRY_COUNT = Number(import.meta.env.VITE_API_READ_RETRY_COUNT ?? "1");
const API_RETRY_DELAY_MS = Number(import.meta.env.VITE_API_RETRY_DELAY_MS ?? "300");

type ApiErrorEnvelope = {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
};

export class ApiRequestError extends Error {
  statusCode?: number;
  code?: string;
  details?: unknown;
  isTimeout: boolean;
  isNetworkError: boolean;

  constructor(params: {
    message: string;
    statusCode?: number;
    code?: string;
    details?: unknown;
    isTimeout?: boolean;
    isNetworkError?: boolean;
  }) {
    super(params.message);
    this.name = "ApiRequestError";
    this.statusCode = params.statusCode;
    this.code = params.code;
    this.details = params.details;
    this.isTimeout = params.isTimeout ?? false;
    this.isNetworkError = params.isNetworkError ?? false;
  }
}

export const getApiErrorMessage = (
  error: unknown,
  fallbackMessage = "Request failed"
): string => {
  if (error instanceof ApiRequestError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallbackMessage;
};

const apiClient = axios.create({
  baseURL: API_URL,
  timeout: API_TIMEOUT_MS,
  headers: {
    "Content-Type": "application/json",
  },
});

const sleep = async (ms: number): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, ms));
};

const toApiRequestError = (error: unknown): ApiRequestError => {
  if (!axios.isAxiosError(error)) {
    if (error instanceof Error) {
      return new ApiRequestError({ message: error.message });
    }
    return new ApiRequestError({ message: "Unexpected error while communicating with API" });
  }

  const statusCode = error.response?.status;
  const responseData = error.response?.data as ApiErrorEnvelope | undefined;
  const envelope = responseData?.error;

  const isTimeout = error.code === "ECONNABORTED";
  const isNetworkError = !error.response;

  if (isTimeout) {
    return new ApiRequestError({
      message: "The request timed out. Please try again.",
      statusCode,
      code: envelope?.code,
      details: envelope?.details,
      isTimeout: true,
      isNetworkError,
    });
  }

  if (envelope?.message) {
    return new ApiRequestError({
      message: envelope.message,
      statusCode,
      code: envelope.code,
      details: envelope.details,
      isTimeout,
      isNetworkError,
    });
  }

  if (isNetworkError) {
    return new ApiRequestError({
      message: "Unable to reach the API. Check your connection and try again.",
      statusCode,
      isTimeout,
      isNetworkError: true,
    });
  }

  return new ApiRequestError({
    message: error.message || "Request failed",
    statusCode,
    isTimeout,
    isNetworkError,
  });
};

const shouldRetry = (
  error: ApiRequestError,
  attempt: number,
  retryCount: number
): boolean => {
  if (attempt >= retryCount) {
    return false;
  }

  if (error.isTimeout || error.isNetworkError) {
    return true;
  }

  if (typeof error.statusCode === "number" && error.statusCode >= 500) {
    return true;
  }

  return false;
};

const executeApiRequest = async <T>(
  request: () => Promise<T>,
  options?: { retries?: number; retryDelayMs?: number }
): Promise<T> => {
  const retryCount = options?.retries ?? 0;
  const retryDelayMs = options?.retryDelayMs ?? API_RETRY_DELAY_MS;

  for (let attempt = 0; ; attempt += 1) {
    try {
      return await request();
    } catch (error) {
      const normalizedError = toApiRequestError(error);
      if (!shouldRetry(normalizedError, attempt, retryCount)) {
        throw normalizedError;
      }
      await sleep(retryDelayMs * (attempt + 1));
    }
  }
};

export const transcribeVideoUrl = async (
  videoUrl: string,
  model?: WhisperModelType,
  language?: string
): Promise<TranscriptionResponse> => {
  // Convert empty string to null for language
  // This ensures FastAPI/Pydantic properly recognizes it as Optional[str]
  const requestBody: TranscriptionRequest = {
    videoUrl,
    model,
    language: language === "" ? null : language,
  };

  return executeApiRequest(async () => {
    const response = await apiClient.post<TranscriptionResponse>(
      "/transcribe/video-url",
      requestBody
    );
    return response.data;
  });
};

export const transcribeVideoFile = async (
  videoFile: File,
  model?: WhisperModelType,
  language?: string
): Promise<TranscriptionResponse> => {
  const formData = new FormData();
  formData.append("video_file", videoFile);

  if (model) {
    formData.append("model", model);
  }

  if (language && language !== "") {
    formData.append("language", language);
  }

  return executeApiRequest(async () => {
    const response = await apiClient.post<TranscriptionResponse>(
      "/transcribe/video-file",
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      }
    );
    return response.data;
  });
};

export const queryTranscript = async (
  question: string,
  videoIds?: string[] | null,
  topK: number = 5,
  searchType: SearchType = "keyword"
): Promise<QuestionResponse> => {
  const requestBody: QuestionRequest = {
    question,
    videoIds: videoIds || undefined,
    topK,
    searchType,
  };

  return executeApiRequest(async () => {
    const response = await apiClient.post<QuestionResponse>(
      "/search/query",
      requestBody
    );
    return response.data;
  });
};

export const getCurrentLlmInfo = async (): Promise<LlmInfo | null> => {
  return executeApiRequest(async () => {
    const response = await apiClient.get("/llms/current");
    return response.data;
  }, { retries: API_READ_RETRY_COUNT });
};

export const listLlms = async (): Promise<LlmListResponse> => {
  return executeApiRequest(async () => {
    const response = await apiClient.get("/llms");
    return response.data;
  }, { retries: API_READ_RETRY_COUNT });
};

export const selectLlm = async (
  modelId: string
): Promise<LlmSelectResponse> => {
  return executeApiRequest(async () => {
    const response = await apiClient.post("/llms/select", { modelId });
    return response.data;
  });
};

export const summarizeTranscript = async (
  videoId: string
): Promise<SummarizationResponse> => {
  const requestBody: SummarizationRequest = {
    videoId,
  };

  return executeApiRequest(async () => {
    const response = await apiClient.post<SummarizationResponse>(
      "/summarize/transcript",
      requestBody
    );
    return response.data;
  });
};

// Video Library API functions

export const getVideoLibrary = async (): Promise<VideoLibraryResponse> => {
  return executeApiRequest(async () => {
    const response = await apiClient.get<VideoLibraryResponse>(
      "/library/videos"
    );
    return response.data;
  }, { retries: API_READ_RETRY_COUNT });
};

export const getVideoGroups = async (): Promise<VideoGroupsResponse> => {
  return executeApiRequest(async () => {
    const response = await apiClient.get<VideoGroupsResponse>(
      "/library/videos/grouped"
    );
    return response.data;
  }, { retries: API_READ_RETRY_COUNT });
};

export const addYouTubeVideo = async (
  url: string,
  model: string = "base"
): Promise<AddVideoResponse> => {
  return executeApiRequest(async () => {
    const response = await apiClient.post<AddVideoResponse>(
      "/library/videos/youtube",
      { url, model }
    );
    return response.data;
  });
};

export const uploadVideos = async (
  files: File[],
  model: string = "base"
): Promise<AddVideosResponse> => {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });
  formData.append("model", model);

  return executeApiRequest(async () => {
    const response = await apiClient.post<AddVideosResponse>(
      "/library/videos/upload",
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      }
    );
    return response.data;
  });
};

export const deleteVideo = async (videoId: string): Promise<void> => {
  return executeApiRequest(async () => {
    await apiClient.delete(`/library/videos/${videoId}`);
  });
};

export const getProcessingStatus =
  async (): Promise<ProcessingStatusResponse> => {
    return executeApiRequest(async () => {
      const response = await apiClient.get<ProcessingStatusResponse>(
        "/library/status"
      );
      return response.data;
    }, { retries: API_READ_RETRY_COUNT });
  };

export const retryVideo = async (videoId: string): Promise<void> => {
  return executeApiRequest(async () => {
    await apiClient.post(`/library/videos/${videoId}/retry`);
  });
};

export const getVideoTranscript = async (
  videoId: string
): Promise<VideoTranscriptResponse> => {
  return executeApiRequest(async () => {
    const response = await apiClient.get<VideoTranscriptResponse>(
      `/library/videos/${videoId}/transcript`
    );
    return response.data;
  }, { retries: API_READ_RETRY_COUNT });
};

export const clearLibrary = async (): Promise<{
  message: string;
  deletedCount: number;
  errors: Array<{ videoId: string; error: string }>;
}> => {
  return executeApiRequest(async () => {
    const response = await apiClient.delete("/library/clear");
    return response.data;
  });
};

// Helper functions for media URLs
export const getVideoStreamUrl = (videoId: string): string => {
  return `${API_URL}/media/video/${videoId}`;
};

export const getThumbnailUrl = (videoId: string): string => {
  return `${API_URL}/media/thumbnail/${videoId}`;
};
