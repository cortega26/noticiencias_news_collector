/** Publication-specific waiting presentation. Used by the triage polling owner. */
import { escapeHtml } from './imageDesk';
import type { AdminPublishBatchItem, AdminPublishStatus } from './types';

export function isPublishActive(status: AdminPublishStatus['status']): boolean {
  return status === 'queued' || status === 'running';
}

export function shouldPollPublish(status: AdminPublishStatus['status']): boolean {
  return isPublishActive(status) || status === 'waiting_for_image';
}

const IMAGE_REASONS: Record<string, string> = {
  missing_source_image: 'Falta una imagen',
  image_download_failed: 'No se pudo descargar la imagen',
  placeholder_image_debt: 'La imagen provisional requiere reemplazo',
  missing_alt_text: 'Falta el texto alternativo de la imagen',
  third_party_image_blocked: 'Derechos de redistribución pendientes',
  unproven_image_rights: 'Derechos de redistribución pendientes',
};

function imageDependency(reason?: string | null, slug?: string | null): string {
  const label = IMAGE_REASONS[reason ?? ''] ?? reason ?? 'Imagen pendiente de resolución';
  return `${escapeHtml(label)} · <a class="text-amber-400 underline" href="/images${slug ? `#${encodeURIComponent(slug)}` : ''}">Ver brief de imagen</a>`;
}

export function renderPublishItems(items: unknown): string {
  if (!Array.isArray(items)) return '';
  return (items as Partial<AdminPublishBatchItem>[])
    .map((item) => {
      const id = escapeHtml(item.article_id ?? '?');
      if (item.status === 'waiting_for_image') {
        return `#${id} · ${imageDependency(item.image_reason, item.image_brief_slug)}`;
      }
      if (item.status === 'succeeded')
        return item.pr_url
          ? `#${id} · <a class="text-amber-400 underline" href="${escapeHtml(item.pr_url)}" target="_blank" rel="noopener">PR abierto</a>`
          : `#${id} · Envío completado sin URL de PR`;
      return `#${id} · ${escapeHtml(item.failure_class ?? item.message ?? 'Error editorial')}`;
    })
    .join('<br>');
}

export function renderWaitingPublication(st: AdminPublishStatus): string {
  const summary = st.summary as Record<string, unknown> | undefined;
  const lines =
    renderPublishItems(summary?.items) || imageDependency(st.image_reason, st.image_brief_slug);
  return `<strong>Edición completada · esperando imagen</strong> (proceso ${escapeHtml(st.run_id)})<br>${lines}<br>El envío se reanudará automáticamente al resolver la imagen.`;
}
