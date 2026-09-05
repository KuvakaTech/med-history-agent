"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const MAX_QUESTION_FAILURES = 3;
export const VOICE_INACTIVITY_MS = 5_000;

export const SILENCE_RETRY_MESSAGE =
  "We didn't hear a response. Please tap Speak and answer when ready.";
export const UNCLEAR_RETRY_MESSAGE = "We couldn't understand that. Please try again.";

export function useQuestionRetry(
  question: string,
  onAutoSkip: () => void,
  replayQuestion: (text: string) => void,
) {
  const failureCountRef = useRef(0);
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const [autoSkipNotice, setAutoSkipNotice] = useState(false);

  useEffect(() => {
    failureCountRef.current = 0;
    setRetryMessage(null);
    setAutoSkipNotice(false);
  }, [question]);

  const handleFailure = useCallback(
    (message: string) => {
      failureCountRef.current += 1;
      if (failureCountRef.current >= MAX_QUESTION_FAILURES) {
        setAutoSkipNotice(true);
        setRetryMessage(null);
        onAutoSkip();
        return;
      }
      setRetryMessage(message);
      replayQuestion(question);
    },
    [question, onAutoSkip, replayQuestion],
  );

  const handleSuccess = useCallback(() => {
    failureCountRef.current = 0;
    setRetryMessage(null);
    setAutoSkipNotice(false);
  }, []);

  return { retryMessage, autoSkipNotice, handleFailure, handleSuccess };
}
