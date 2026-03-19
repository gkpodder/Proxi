marked.setOptions({ gfm: true, breaks: false });

(function registerUtils(global) {
  const OTHER_OPTION = "Other (type your own)";
  const TIMEZONE_OPTIONS = [
    "America/Toronto",
    "America/Vancouver",
    "America/New_York",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Kolkata",
    "Asia/Tokyo",
    "Australia/Sydney",
    "UTC",
  ];

  function renderMarkdown(text) {
    if (!text) return "";
    const raw = marked.parse(text);
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  }

  function evaluateShowIf(showIf, answers) {
    if (!showIf) return true;
    const qId = showIf.question_id;
    if (!qId || !(qId in answers)) return false;
    const answer = answers[qId];

    if (Object.prototype.hasOwnProperty.call(showIf, "equals")) {
      return answer === showIf.equals;
    }
    if (Object.prototype.hasOwnProperty.call(showIf, "not_equals")) {
      return answer !== showIf.not_equals;
    }
    return true;
  }

  function getVisibleQuestions(questions, answers) {
    return (questions || []).filter((q) => evaluateShowIf(q.show_if, answers));
  }

  function getOptionsWithOther(question) {
    if (!question) return [];
    if (question.type === "choice" || question.type === "multiselect") {
      return [...(question.options || []), OTHER_OPTION];
    }
    return [];
  }

  global.ProxiUtils = {
    OTHER_OPTION,
    TIMEZONE_OPTIONS,
    renderMarkdown,
    evaluateShowIf,
    getVisibleQuestions,
    getOptionsWithOther,
  };
})(window);
