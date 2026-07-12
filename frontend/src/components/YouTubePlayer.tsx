import { useEffect, useRef, useImperativeHandle, forwardRef } from "react";

interface YouTubePlayerProps {
  videoUrl: string;
}

export interface YouTubePlayerHandle {
  seekTo: (seconds: number) => void;
}

interface YouTubePlayerInstance {
  seekTo: (seconds: number, allowSeekAhead: boolean) => void;
  destroy: () => void;
}

interface YouTubePlayerConstructor {
  new (
    container: HTMLElement,
    options: {
      videoId: string;
      playerVars: {
        playsinline: 1;
        rel: 0;
      };
    }
  ): YouTubePlayerInstance;
}

interface YouTubeNamespace {
  Player: YouTubePlayerConstructor;
}

declare global {
  interface Window {
    YT?: YouTubeNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

/**
 * Extract YouTube video ID from various URL formats
 */
function extractVideoId(url: string): string | null {
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)/,
    /^([a-zA-Z0-9_-]{11})$/, // Direct video ID
  ];

  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }
  return null;
}

const YouTubePlayer = forwardRef<YouTubePlayerHandle, YouTubePlayerProps>(
  ({ videoUrl }, ref) => {
    const playerRef = useRef<YouTubePlayerInstance | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const videoId = extractVideoId(videoUrl);

    useImperativeHandle(ref, () => ({
      seekTo: (seconds: number) => {
        if (playerRef.current && playerRef.current.seekTo) {
          playerRef.current.seekTo(seconds, true);
        }
      },
    }));

    useEffect(() => {
      const resolvedVideoId = videoId;
      if (!resolvedVideoId) return;
      const playerVideoId: string = resolvedVideoId;

      // Load YouTube iframe API
      if (!window.YT) {
        const tag = document.createElement("script");
        tag.src = "https://www.youtube.com/iframe_api";
        const firstScriptTag = document.getElementsByTagName("script")[0];
        firstScriptTag.parentNode?.insertBefore(tag, firstScriptTag);

        window.onYouTubeIframeAPIReady = () => {
          createPlayer();
        };
      } else {
        createPlayer();
      }

      function createPlayer() {
        if (containerRef.current && window.YT) {
          playerRef.current = new window.YT.Player(containerRef.current, {
            videoId: playerVideoId,
            playerVars: {
              playsinline: 1,
              rel: 0,
            },
          });
        }
      }

      return () => {
        if (playerRef.current && playerRef.current.destroy) {
          playerRef.current.destroy();
        }
      };
    }, [videoId]);

    if (!videoId) {
      return (
        <div className="w-full h-full flex items-center justify-center bg-gray-900 text-gray-400 dark:bg-gray-950 dark:text-gray-500">
          <p>Invalid YouTube URL</p>
        </div>
      );
    }

    return (
      <div className="w-full h-full">
        <div
          ref={containerRef}
          className="w-full h-full"
          style={{ minHeight: "100%" }}
        />
      </div>
    );
  }
);

YouTubePlayer.displayName = "YouTubePlayer";

export default YouTubePlayer;
