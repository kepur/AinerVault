// Review hints only. Never rewrite or unlock a finalized translation automatically.
export function translationIssues(text: string | null): string[] {
  if (!text) return [];
  const issues: string[] = [];
  if (/\b(?:DadMom|MomDad)\b/i.test(text)) issues.push("亲属称谓出现粘连，请核对父母的称呼。");
  if (/\b(?:his|her|my|your|our|their)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s+(?:was|is|asked|said|works|had|for)\b/.test(text)
    || /\b[A-Z][a-z]+\s+[A-Z][a-z]+'s\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s+(?:was|is|asked|said)\b/.test(text)) {
    issues.push("疑似把亲属称谓替换成了人名，请结合原文检查。");
  }
  return issues;
}
