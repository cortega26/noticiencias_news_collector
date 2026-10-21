import type { AdminImageBriefItem } from './types';

/** Escape text for safe interpolation into HTML text and attribute values. */
export function escapeHtml(value: unknown): string {
  if (value == null) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Provenance options for the Images desk. Order is the operator-facing order
 * from plan 169; `ai_generated` drives the visible AI label on publication.
 */
export const IMAGE_ORIGIN_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'ai_generated', label: 'IA generada' },
  { value: 'licensed', label: 'Licencia' },
  { value: 'original', label: 'Original' },
  { value: 'unknown', label: 'Desconocido' },
];

export function imageOriginLabel(value: string | null | undefined): string {
  return (
    IMAGE_ORIGIN_OPTIONS.find((option) => option.value === (value ?? 'unknown'))?.label ??
    'Desconocido'
  );
}

/**
 * Render one Images-desk card.
 *
 * Every interpolated value is escaped. The generated prompt lives in a
 * `<pre data-prompt>` whose `textContent` is the exact stored prompt — the
 * copy button reads it back from the DOM, so the clipboard payload is the
 * original text (never the escaped/rendered markup).
 */
export function renderImageCard(b: AdminImageBriefItem): string {
  const prompt = (b.generated_prompt ?? '').trim();
  const origin = b.image_origin ?? 'unknown';
  const originOptions = IMAGE_ORIGIN_OPTIONS.map(
    (option) =>
      `<option value="${option.value}"${option.value === origin ? ' selected' : ''}>${option.label}</option>`
  ).join('');
  return `
    <div class="card p-4" id="${escapeHtml(b.slug)}" data-slug="${escapeHtml(b.slug)}">
      <div class="mb-2 flex items-center justify-between">
        <span class="status-pill status-${b.status === 'editorial_image_ready' ? 'completed' : 'new'}">${b.status === 'editorial_image_ready' ? 'Lista' : escapeHtml(b.status)}</span>
        <span class="font-mono text-[11px] text-ink-400">${escapeHtml(b.updated_at ?? '—')}</span>
      </div>
      <div class="font-mono text-xs text-amber-400">${escapeHtml(b.slug)}</div>
      <div class="mt-1 text-sm font-medium text-ink-100">${escapeHtml(b.topic)}</div>
      <div class="mt-2 font-mono text-[11px] text-ink-400">artículo ${escapeHtml(b.article_id)} · ${escapeHtml(b.reason)} · origen ${escapeHtml(imageOriginLabel(origin))}</div>

      ${
        prompt
          ? `<details class="mt-3">
              <summary class="data-label cursor-pointer">PROMPT DE IMAGEN</summary>
              <div class="mt-2 flex items-center justify-between gap-2">
                <span class="font-mono text-[11px] text-ink-400">${escapeHtml(b.slug)}</span>
                <button class="btn-ghost !px-2.5 !py-1 text-xs" data-copy="${escapeHtml(b.slug)}" type="button">Copiar prompt</button>
              </div>
              <pre data-prompt class="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded border border-ink-700 bg-ink-900 p-2 font-mono text-[11px] text-ink-200">${escapeHtml(prompt)}</pre>
            </details>`
          : `<p class="mt-3 font-mono text-[11px] text-ink-400">Prompt no disponible para este brief.</p>`
      }

      <div class="mt-3 space-y-2">
        <label class="block">
          <span class="data-label block mb-1">TEMA</span>
          <input data-field="topic" value="${escapeHtml(b.topic)}" class="w-full rounded border border-ink-700 bg-ink-900 px-2.5 py-1.5 font-mono text-xs text-ink-100 focus:border-amber-500 outline-none" />
        </label>
        <label class="block">
          <span class="data-label block mb-1">ENFOQUE</span>
          <input data-field="news_angle" value="${escapeHtml(b.news_angle ?? '')}" class="w-full rounded border border-ink-700 bg-ink-900 px-2.5 py-1.5 font-mono text-xs text-ink-100 focus:border-amber-500 outline-none" />
        </label>
        <label class="block">
          <span class="data-label block mb-1">TEXTO ALT</span>
          <input data-field="draft_alt_text" value="${escapeHtml(b.draft_alt_text ?? '')}" class="w-full rounded border border-ink-700 bg-ink-900 px-2.5 py-1.5 font-mono text-xs text-ink-100 focus:border-amber-500 outline-none" />
        </label>
        <label class="block">
          <span class="data-label block mb-1">ORIGEN</span>
          <select data-field="image_origin" class="w-full rounded border border-ink-700 bg-ink-900 px-2.5 py-1.5 font-mono text-xs text-ink-100 focus:border-amber-500 outline-none">${originOptions}</select>
        </label>
        <div class="flex flex-wrap gap-2">
          <button class="btn-ghost !px-2.5 !py-1 text-xs" data-save="${escapeHtml(b.slug)}" type="button">Guardar cambios</button>
          <label class="btn-ghost !px-2.5 !py-1 text-xs cursor-pointer">
            Añadir archivo
            <input type="file" accept="image/*" class="hidden" data-upload="${escapeHtml(b.slug)}" />
          </label>
          ${
            b.status === 'editorial_image_ready'
              ? `<button class="btn-primary !px-2.5 !py-1 text-xs" data-publish="${escapeHtml(b.article_id)}" type="button">Consultar envío</button>`
              : ''
          }
        </div>
      </div>
    </div>`;
}
