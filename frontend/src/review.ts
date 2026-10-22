/** Built-in state definitions; kept separate from editable project tags. */
export const reviewStates = [
  {
    value: "pending",
    label: "Not reviewed",
    color: "#64748b",
    description: "Awaiting human review.",
  },
  {
    value: "ok",
    label: "Approved",
    color: "#24835d",
    description: "Reviewed and accepted for this task.",
  },
  {
    value: "uncertain",
    label: "Needs review",
    color: "#ad711b",
    description: "Needs another human check for this task.",
  },
  {
    value: "excluded",
    label: "Excluded",
    color: "#b34e5d",
    description: "Excluded from processing and export.",
  },
] as const;
