/** Arrow tip stays at the image coordinate; the badge identifies the active tool. */
const marks: Record<string, { color: string; shape: string }> = {
  box: {
    color: "#315fe9",
    shape:
      '<rect x="18" y="3" width="11" height="10" fill="none" stroke-width="1.7"/>',
  },
  promptbox: {
    color: "#a86a0a",
    shape:
      '<path d="M22 3H18V7M25 3H29V7M18 10V14H22M25 14H29V10" fill="none" stroke-width="1.7"/><path d="M21 8H26M23.5 5.5V10.5" stroke-width="1.4"/>',
  },
  positive: {
    color: "#24835d",
    shape: '<path d="M18 8H29M23.5 2.5V13.5" stroke-width="2"/>',
  },
  negative: {
    color: "#c14d5c",
    shape: '<path d="M18 8H29" stroke-width="2"/>',
  },
  text: {
    color: "#526279",
    shape:
      '<path d="M18 3H29M23.5 3V14M21 14H26" fill="none" stroke-width="1.7"/>',
  },
  prompts: {
    color: "#a86a0a",
    shape:
      '<circle cx="23.5" cy="8" r="5" fill="none" stroke-dasharray="2 2" stroke-width="1.6"/>',
  },
};
export const toolCursors = Object.fromEntries(
  Object.entries(marks).map(([tool, mark]) => {
    const arrow = "M2 2L2 19L6.5 14.5L10 22L13 20.5L9.5 13H17Z";
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path d="${arrow}" fill="#25344a" stroke="white" stroke-width="2.5" stroke-linejoin="round"/><rect x="16" y="0.5" width="15" height="16" rx="3" fill="white" fill-opacity=".95"/><g stroke="${mark.color}" stroke-linecap="round" stroke-linejoin="round">${mark.shape}</g></svg>`;
    return [
      tool,
      `url("data:image/svg+xml,${encodeURIComponent(svg)}") 2 2, default`,
    ];
  }),
);
