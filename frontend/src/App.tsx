import React, { useState, useRef, useEffect, useCallback } from "react";
import "./App.css";
import VideoLibrary from "./components/VideoLibrary";
import VideoPlayer, { type VideoPlayerHandle } from "./components/VideoPlayer";
import AddVideoModal from "./components/AddVideoModal";
import SearchPanel from "./components/SearchPanel";
import ThemeToggle from "./components/ThemeToggle";
import type { VideoMetadata, VideosByGroup } from "./types/library.types";
import {
  getApiErrorMessage,
  getVideoGroups,
  getProcessingStatus,
} from "./services/api";

const POLL_INTERVAL_PROCESSING_MS = 3000;
const POLL_INTERVAL_IDLE_MS = 10000;
const POLL_INTERVAL_HIDDEN_MS = 30000;

const App: React.FC = () => {
  const [videoGroups, setVideoGroups] = useState<VideosByGroup[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<VideoMetadata | null>(
    null
  );
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [processingCount, setProcessingCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const videoPlayerRef = useRef<VideoPlayerHandle>(null);
  const prevProcessingCountRef = useRef<number>(0);

  const fetchVideoLibrary = useCallback(async () => {
    try {
      const response = await getVideoGroups();
      setVideoGroups(response.groups);

      // Update selected video if it was updated.
      setSelectedVideo((previousVideo) => {
        if (!previousVideo) {
          return previousVideo;
        }
        const allVideos = response.groups.flatMap((g) => g.videos);
        const updatedVideo = allVideos.find((v) => v.id === previousVideo.id);
        if (updatedVideo) {
          return updatedVideo;
        }
        return previousVideo;
      });
    } catch (err) {
      setError(getApiErrorMessage(err, "Failed to fetch video library"));
    }
  }, []);

  const fetchProcessingStatus = useCallback(async () => {
    try {
      const status = await getProcessingStatus();
      setProcessingCount(status.queueLength + status.processing.length);
      return status.queueLength + status.processing.length;
    } catch (err) {
      setError(getApiErrorMessage(err, "Failed to fetch processing status"));
      return 0;
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    void fetchVideoLibrary();
  }, [fetchVideoLibrary]);

  // Polling for updates when processing
  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let isCancelled = false;

    const scheduleNextPoll = (count: number) => {
      if (isCancelled) {
        return;
      }

      const nextInterval =
        count > 0
          ? POLL_INTERVAL_PROCESSING_MS
          : document.visibilityState === "hidden"
            ? POLL_INTERVAL_HIDDEN_MS
            : POLL_INTERVAL_IDLE_MS;

      timeoutId = setTimeout(() => {
        void poll();
      }, nextInterval);
    };

    const poll = async () => {
      const count = await fetchProcessingStatus();
      const prevCount = prevProcessingCountRef.current;

      // Fetch library if processing, OR if we just finished (transition from >0 to 0)
      if (count > 0 || (prevCount > 0 && count === 0)) {
        await fetchVideoLibrary();
      }

      prevProcessingCountRef.current = count;
      scheduleNextPoll(count);
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible") {
        return;
      }

      if (timeoutId) {
        clearTimeout(timeoutId);
      }

      timeoutId = setTimeout(() => {
        void poll();
      }, 0);
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    void poll();

    return () => {
      isCancelled = true;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [fetchProcessingStatus, fetchVideoLibrary]);

  const handleSelectVideo = (video: VideoMetadata) => {
    setSelectedVideo(video);
    setError(null);
    setIsSidebarOpen(false); // Close sidebar on mobile when selecting a video
  };

  const handleSeekToTime = (seconds: number, videoId?: string) => {
    // If a different video, switch to it first
    if (videoId && videoId !== selectedVideo?.id) {
      const allVideos = videoGroups.flatMap((g) => g.videos);
      const targetVideo = allVideos.find((v) => v.id === videoId);
      if (targetVideo) {
        setSelectedVideo(targetVideo);
        // Wait for video to load, then seek
        setTimeout(() => {
          videoPlayerRef.current?.seekTo(seconds);
        }, 500);
        return;
      }
    }

    if (videoPlayerRef.current) {
      videoPlayerRef.current.seekTo(seconds);
    }
  };

  const handleVideoAdded = () => {
    fetchVideoLibrary();
    fetchProcessingStatus();
  };

  // Get all completed video IDs for search
  const completedVideoIds = videoGroups
    .flatMap((g) => g.videos)
    .filter((v) => v.status === "completed")
    .map((v) => v.id);

  return (
    <div className="h-screen flex bg-gray-100 dark:bg-gray-900">
      {/* Mobile sidebar backdrop */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-20 lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* Left Sidebar - Video Library */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-30 w-72 bg-white border-r border-gray-200 dark:bg-gray-800 dark:border-gray-700
          transform transition-transform duration-300 ease-in-out
          lg:relative lg:translate-x-0 lg:flex-shrink-0
          ${isSidebarOpen ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        <VideoLibrary
          groups={videoGroups}
          selectedVideoId={selectedVideo?.id || null}
          onSelectVideo={handleSelectVideo}
          onAddVideos={() => setIsAddModalOpen(true)}
          onRefresh={fetchVideoLibrary}
          processingCount={processingCount}
        />
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Header */}
        <header className="flex-shrink-0 bg-white border-b border-gray-200 px-4 lg:px-6 py-3 dark:bg-gray-800 dark:border-gray-700">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 lg:gap-4">
              {/* Mobile menu button */}
              <button
                onClick={() => setIsSidebarOpen(true)}
                className="lg:hidden p-2 -ml-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-md dark:text-gray-300 dark:hover:text-white dark:hover:bg-gray-700"
                aria-label="Open sidebar"
              >
                <svg
                  className="w-6 h-6"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 6h16M4 12h16M4 18h16"
                  />
                </svg>
              </button>
              <img
                src="/hpi_logo.png"
                alt="HPI KISZ Logo"
                className="h-8 lg:h-10 w-auto"
              />
              <div className="hidden sm:block">
                <h1 className="text-lg lg:text-xl font-semibold text-gray-900 dark:text-gray-100">
                  Video Search
                </h1>
                <p className="text-xs lg:text-sm text-gray-500 dark:text-gray-400">
                  Search across your video library
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 lg:gap-3">
              <ThemeToggle />
              <img
                src="/bmbf_logo.png"
                alt="BMBF Logo"
                className="h-8 lg:h-10 w-auto"
              />
            </div>
          </div>
        </header>

        {/* Error banner */}
        {error && (
          <div className="flex-shrink-0 bg-red-50 border-b border-red-200 px-4 lg:px-6 py-3 dark:bg-red-950 dark:border-red-900">
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        )}

        {/* Video Player */}
        <div className="flex-shrink-0 h-[30vh] sm:h-[35vh] lg:h-[40vh] min-h-[180px] lg:min-h-[250px] max-h-[500px] bg-gray-900 flex items-center justify-center">
          <VideoPlayer ref={videoPlayerRef} video={selectedVideo} />
        </div>

        {/* Search Panel */}
        <div className="flex-1 overflow-hidden min-h-0">
          <SearchPanel
            selectedVideo={selectedVideo}
            allVideoIds={completedVideoIds}
            onSeekToTime={handleSeekToTime}
            onError={(err) => setError(err?.message || null)}
          />
        </div>
      </main>

      {/* Add Video Modal */}
      <AddVideoModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onVideoAdded={handleVideoAdded}
      />
    </div>
  );
};

export default App;
