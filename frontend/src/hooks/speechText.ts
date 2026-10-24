// Texto pronto para ser falado pela voz do navegador (mesmas regras do backend em
// app/voice/speech_text.py, usado pelo Piper): sem símbolos, citações nem links.
const money = (_: string, r: string, c?: string) => {
  const reais = Number(r.replace(/\./g, ""));
  const cents = Number(c ?? 0);
  return `${reais} ${reais === 1 ? "real" : "reais"}${cents ? ` e ${cents} ${cents === 1 ? "centavo" : "centavos"}` : ""}`;
};

export function toSpeech(text: string, maxChars = 900): string {
  let t = text.replace(/```[\s\S]*?```/g, " (trecho de código na tela) ");
  t = t.replace(/`([^`]{1,40})`/g, "$1").replace(/https?:\/\/\S+/g, " (link na tela) ");
  t = t.replace(/\[[^\]]{0,80}\]/g, "").replace(/\p{Extended_Pictographic}/gu, " ").replace(/[✔✖✓✗→←⇒•▪◦]/g, " ");
  t = t.replace(/^\s*[-*•]\s+/gm, "").replace(/[*#>_~|]+/g, " ");
  t = t.replace(/R\$\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?/g, money);
  t = t.replace(/\b([01]?\d|2[0-3])[:h]([0-5]\d)\b/g, (_, h: string, m: string) =>
    Number(m) === 0 ? `${Number(h)} ${Number(h) === 1 ? "hora" : "horas"}` : `${Number(h)} e ${Number(m)}`);
  t = t.replace(/(\d+(?:[.,]\d+)?)\s*[°º]\s*C\b/g, "$1 graus").replace(/(\d+(?:[.,]\d+)?)\s*[°º]/g, "$1 graus");
  t = t.replace(/(\d+(?:[.,]\d+)?)\s*%/g, "$1 por cento");
  t = t.replace(/\s*\n+\s*/g, ". ").replace(/\.(\s*\.)+/g, ".").replace(/([:;,])\s*\./g, "$1").replace(/\s+([,.!?;:])/g, "$1");
  t = t.replace(/\(\s*([^)]*?)\s*\)/g, (_, inner: string) => (inner ? `(${inner})` : "")).replace(/\s+/g, " ").trim();
  return t.length > maxChars ? `${t.slice(0, maxChars).replace(/\s+\S*$/, "")}… Os detalhes estão na tela.` : t;
}
