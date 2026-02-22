/**
 * Agent-invoked collaborative form overlay.
 * Renders when the bridge emits user_input_required with a payload.questions array.
 * Supports choice, multiselect, yesno, text. Appends "Other (type your own)" for choice/multiselect.
 */
import React, { useState, useCallback, useRef, useMemo, useEffect } from "react";
import { Box, Text, useInput, useFocusManager } from "ink";
import TextInput from "ink-text-input";
import type { CollaborativeFormPayload, Question } from "../protocol.js";

const OTHER_OPTION = "Other (type your own)";

function evaluateShowIf(
  showIf: Record<string, unknown> | null | undefined,
  answers: Record<string, unknown>
): boolean {
  if (!showIf) return true;
  const qId = showIf.question_id as string | undefined;
  if (!qId || !(qId in answers)) return false;
  const answer = answers[qId];
  if ("equals" in showIf) return answer === showIf.equals;
  if ("not_equals" in showIf) return answer !== showIf.not_equals;
  return true;
}

function getVisibleQuestions(
  questions: Question[],
  answers: Record<string, unknown>
): Question[] {
  return questions.filter((q) => evaluateShowIf(q.show_if ?? undefined, answers));
}

function getOptionsWithOther(
  q: Question
): string[] {
  if (q.type === "choice" || q.type === "multiselect") {
    const opts = q.options ?? [];
    return [...opts, OTHER_OPTION];
  }
  return [];
}

type Props = {
  payload: CollaborativeFormPayload;
  onSubmit: (result: {
    tool_call_id: string;
    answers: Record<string, unknown>;
    skipped: boolean;
  }) => void;
};

export function AnswerForm({ payload, onSubmit }: Props) {
  const { tool_call_id, goal, title, questions, allow_skip = false } = payload;
  const { disableFocus, enableFocus } = useFocusManager();

  useEffect(() => {
    disableFocus();
    return () => enableFocus();
  }, [disableFocus, enableFocus]);

  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectIndex, setSelectIndex] = useState(0);
  const [multiselectSet, setMultiselectSet] = useState<Set<number>>(new Set());
  const [textValue, setTextValue] = useState("");
  const [otherValue, setOtherValue] = useState("");
  const [isOtherSelected, setIsOtherSelected] = useState(false);

  const visibleQuestions = useMemo(
    () => getVisibleQuestions(questions, answers),
    [questions, answers]
  );
  const totalVisible = visibleQuestions.length;
  // Clamp currentIndex when visibleQuestions shrinks (e.g. show_if filters change)
  const safeIndex = Math.min(currentIndex, Math.max(0, totalVisible - 1));
  const currentQ = visibleQuestions[safeIndex];

  useEffect(() => {
    if (currentIndex >= totalVisible && totalVisible > 0) {
      setCurrentIndex(totalVisible - 1);
    }
  }, [currentIndex, totalVisible]);
  const optionsWithOther = currentQ
    ? getOptionsWithOther(currentQ)
    : [];
  const otherIndex = optionsWithOther.indexOf(OTHER_OPTION);
  const selectIndexRef = useRef(selectIndex);
  selectIndexRef.current = selectIndex;

  const advanceOrSubmit = useCallback(() => {
    if (!currentQ) return;

    if (currentQ.type === "yesno") return; // yesno uses Y/N keys, not Enter to advance

    if (
      (currentQ.type === "choice" || currentQ.type === "multiselect") &&
      isOtherSelected
    ) {
      if (otherValue.trim() === "") return;
      const val =
        currentQ.type === "choice"
          ? otherValue.trim()
          : Array.from(multiselectSet)
              .map((i) =>
                optionsWithOther[i] === OTHER_OPTION ? otherValue.trim() : optionsWithOther[i]
              )
              .filter(Boolean);
      setAnswers((a) => ({ ...a, [currentQ.id]: val }));
      setIsOtherSelected(false);
      setOtherValue("");
      if (currentIndex >= totalVisible - 1) {
        const finalAnswers: Record<string, unknown> = {
          ...answers,
          [currentQ.id]: val,
        };
        onSubmit({ tool_call_id, answers: finalAnswers, skipped: false });
        return;
      }
      setCurrentIndex((i) => i + 1);
      setSelectIndex(0);
      setMultiselectSet(new Set());
      return;
    }

    if (currentQ.type === "choice" && optionsWithOther.length > 0) {
      const sel = optionsWithOther[selectIndexRef.current];
      if (sel === OTHER_OPTION) {
        setIsOtherSelected(true);
        return;
      }
      setAnswers((a) => ({ ...a, [currentQ.id]: sel }));
    }

    if (currentQ.type === "multiselect" && optionsWithOther.length > 0) {
      const selected = Array.from(multiselectSet)
        .map((i) => optionsWithOther[i])
        .filter(Boolean);
      if (selected.includes(OTHER_OPTION)) {
        setIsOtherSelected(true);
        return;
      }
      setAnswers((a) => ({ ...a, [currentQ.id]: selected }));
    }

    if (currentQ.type === "text") {
      const val = textValue.trim();
      if (currentQ.required !== false && val === "") return;
      setAnswers((a) => ({ ...a, [currentQ.id]: val }));
      setTextValue("");
    }

    if (currentIndex >= totalVisible - 1) {
      let finalVal: unknown;
      if (currentQ.type === "choice")
        finalVal = optionsWithOther[selectIndexRef.current];
      else if (currentQ.type === "multiselect")
        finalVal = Array.from(multiselectSet)
          .map((i) => optionsWithOther[i])
          .filter(Boolean);
      else if (currentQ.type === "text")
        finalVal = textValue.trim();
      else
        finalVal = null;
      const finalAnswers = { ...answers, [currentQ.id]: finalVal };
      onSubmit({ tool_call_id, answers: finalAnswers, skipped: false });
      return;
    }

    setCurrentIndex((i) => i + 1);
    setSelectIndex(0);
    setMultiselectSet(new Set());
    setTextValue("");
  }, [
    currentQ,
    currentIndex,
    totalVisible,
    answers,
    textValue,
    otherValue,
    isOtherSelected,
    multiselectSet,
    tool_call_id,
    onSubmit,
    optionsWithOther,
  ]);

  const goBack = useCallback(() => {
    if (currentIndex <= 0) return;
    setCurrentIndex((i) => i - 1);
    const prevQ = visibleQuestions[currentIndex - 1];
    const opts = prevQ ? getOptionsWithOther(prevQ) : [];
    setSelectIndex(0);
    setMultiselectSet(new Set());
    setTextValue("");
    setIsOtherSelected(false);
    setOtherValue("");
  }, [currentIndex, visibleQuestions]);

  useInput((input, key) => {
    if (key.escape) {
      if (allow_skip) {
        onSubmit({ tool_call_id, answers: {}, skipped: true });
        return;
      }
      if (isOtherSelected) {
        setIsOtherSelected(false);
        setOtherValue("");
        return;
      }
      return;
    }

    if (!currentQ) return;

    if (currentQ.type === "yesno") {
      if (input.toLowerCase() === "y") {
        setAnswers((a) => ({ ...a, [currentQ.id]: true }));
        if (currentIndex >= totalVisible - 1) {
          onSubmit({
            tool_call_id,
            answers: { ...answers, [currentQ.id]: true },
            skipped: false,
          });
        } else {
          setCurrentIndex((i) => i + 1);
        }
      }
      if (input.toLowerCase() === "n") {
        setAnswers((a) => ({ ...a, [currentQ.id]: false }));
        if (currentIndex >= totalVisible - 1) {
          onSubmit({
            tool_call_id,
            answers: { ...answers, [currentQ.id]: false },
            skipped: false,
          });
        } else {
          setCurrentIndex((i) => i + 1);
        }
      }
      return;
    }

    if (key.tab && !key.shift) {
      advanceOrSubmit();
      return;
    }
    if (key.tab && key.shift) {
      goBack();
      return;
    }
    if (key.return && !key.shift) {
      advanceOrSubmit();
      return;
    }

    if (currentQ.type === "choice" && optionsWithOther.length > 0 && !isOtherSelected) {
      if (key.upArrow) setSelectIndex((i) => (i <= 0 ? optionsWithOther.length - 1 : i - 1));
      if (key.downArrow) setSelectIndex((i) => (i >= optionsWithOther.length - 1 ? 0 : i + 1));
      return;
    }

    if (currentQ.type === "multiselect" && optionsWithOther.length > 0 && !isOtherSelected) {
      if (key.upArrow) setSelectIndex((i) => (i <= 0 ? optionsWithOther.length - 1 : i - 1));
      if (key.downArrow) {
        setSelectIndex((i) => (i >= optionsWithOther.length - 1 ? 0 : i + 1));
        return;
      }
      if (input === " ") {
        const idx = selectIndexRef.current;
        if (optionsWithOther[idx] === OTHER_OPTION) {
          setIsOtherSelected(true);
          return;
        }
        setMultiselectSet((s) => {
          const next = new Set(s);
          if (next.has(idx)) next.delete(idx);
          else next.add(idx);
          return next;
        });
        return;
      }
      if (key.return) {
        advanceOrSubmit();
        return;
      }
      return;
    }
  });

  if (visibleQuestions.length === 0) {
    onSubmit({ tool_call_id, answers: {}, skipped: false });
    return null;
  }

  if (!currentQ) {
    onSubmit({ tool_call_id, answers, skipped: false });
    return null;
  }

  const progressDots = visibleQuestions
    .map((_, i) => (i === safeIndex ? "●" : "○"))
    .join(" ");

  return (
    <Box flexDirection="column" paddingX={1} flexShrink={0} borderStyle="round" borderColor="cyan">
      <Box marginBottom={1}>
        <Text bold color="cyan">
          {title || goal}
        </Text>
      </Box>
      <Box marginBottom={0}>
        <Text dimColor>
          Questions ({safeIndex + 1}/{totalVisible}) {progressDots}
        </Text>
      </Box>

      <Box flexDirection="column" marginTop={1}>
        <Text color="yellow">Q: {currentQ?.question ?? "(No question text)"}</Text>
        {currentQ?.hint && (
          <Box marginLeft={2} marginTop={0}>
            <Text dimColor italic>
              — {currentQ.hint}
            </Text>
          </Box>
        )}

        <Box marginTop={1} flexDirection="column">
          <Text color="green">A:</Text>

          {currentQ.type === "yesno" && (
            <Box gap={1} marginTop={0}>
              <Text bold color="green">
                Y
              </Text>
              <Text> Yes</Text>
              <Text dimColor> N No</Text>
              {allow_skip && <Text dimColor> Esc cancel</Text>}
            </Box>
          )}

          {currentQ.type === "choice" &&
            !isOtherSelected &&
            optionsWithOther.map((opt, i) => (
              <Box key={opt}>
                <Text color={i === selectIndex ? "green" : "white"}>
                  {i === selectIndex ? "› " : "  "}
                  {opt}
                </Text>
              </Box>
            ))}

          {currentQ.type === "choice" && isOtherSelected && (
            <Box marginTop={0} flexDirection="column">
              <Text dimColor>Type your answer:</Text>
              <TextInput
                value={otherValue}
                onChange={setOtherValue}
                onSubmit={() => advanceOrSubmit()}
                placeholder={currentQ.placeholder ?? ""}
                showCursor
              />
            </Box>
          )}

          {currentQ.type === "multiselect" &&
            !isOtherSelected &&
            optionsWithOther.map((opt, i) => (
              <Box key={opt}>
                <Text color={i === selectIndex ? "green" : "white"}>
                  {i === selectIndex ? "› " : "  "}
                  {multiselectSet.has(i) ? "[✓] " : "[ ] "}
                  {opt}
                </Text>
              </Box>
            ))}

          {currentQ.type === "multiselect" && isOtherSelected && (
            <Box marginTop={0} flexDirection="column">
              <Text dimColor>Type your custom option:</Text>
              <TextInput
                value={otherValue}
                onChange={setOtherValue}
                onSubmit={() => advanceOrSubmit()}
                placeholder=""
                showCursor
              />
            </Box>
          )}

          {currentQ.type === "text" && (
            <Box marginTop={0} flexDirection="column">
              <TextInput
                value={textValue}
                onChange={setTextValue}
                onSubmit={() => advanceOrSubmit()}
                placeholder={currentQ.placeholder ?? ""}
                showCursor
              />
            </Box>
          )}
        </Box>
      </Box>

      <Box marginTop={1}>
        <Text dimColor>
          Enter confirm · Tab next · Shift+Tab prev
          {currentQ.type === "multiselect" && " · Space toggle"}
          {currentQ.type === "text" && " · Shift+Enter newline"}
          {allow_skip && " · Esc cancel"}
        </Text>
      </Box>
    </Box>
  );
}
