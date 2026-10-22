import { describe, expect, it } from 'vitest';
import { isPublishActive, shouldPollPublish, renderWaitingPublication } from './publishWaiting';
import type { AdminPublishStatus } from './types';

const waiting = {
  run_id: '99',
  status: 'waiting_for_image',
  active: false,
  image_brief_slug: 'roots-3822',
  image_reason: 'missing_source_image',
  editorial_completed_count: 1,
  waiting_for_image_count: 1,
} as AdminPublishStatus;

function mount(status: AdminPublishStatus): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderWaitingPublication(status);
  return host;
}

describe('waiting publication', () => {
  it('continues polling without holding the active publication controls', () => {
    expect(shouldPollPublish(waiting.status)).toBe(true);
    expect(isPublishActive(waiting.status)).toBe(false);
    expect(isPublishActive('running')).toBe(true);
    expect(shouldPollPublish('succeeded')).toBe(false);
    expect(shouldPollPublish('failed')).toBe(false);
  });

  it('renders the explicit waiting state and reason with a brief link, without ETA or stall warning', () => {
    const host = mount(waiting);
    expect(host.textContent).toContain('Edición completada · esperando imagen');
    expect(host.textContent).toContain('Falta una imagen');
    expect(host.querySelector('a')?.getAttribute('href')).toBe('/images#roots-3822');
    expect(host.textContent).not.toMatch(/restantes|colgado|estimado/);
  });

  it('renders mixed batch success, pending and failure independently', () => {
    const host = mount({
      ...waiting,
      summary: {
        items: [
          { article_id: 1, status: 'succeeded', pr_url: 'https://github.com/org/repo/pull/1' },
          {
            article_id: 3822,
            status: 'waiting_for_image',
            image_brief_slug: 'roots-3822',
            image_reason: 'missing_source_image',
          },
          { article_id: 3, status: 'failed', message: 'editorial rejection' },
        ],
      },
    });
    expect(host.textContent).toContain('#1');
    expect(host.textContent).toContain('PR abierto');
    expect(host.textContent).toContain('#3822');
    expect(host.textContent).toContain('#3');
    expect(host.textContent).toContain('editorial rejection');
  });

  it('explains unproven image rights in Spanish', () => {
    const host = mount({ ...waiting, image_reason: 'unproven_image_rights' });
    expect(host.textContent).toContain('Derechos de redistribución pendientes');
    expect(host.textContent).not.toContain('unproven_image_rights');
    expect(host.querySelector('a')?.getAttribute('href')).toBe('/images#roots-3822');
  });

  it('escapes unknown reasons and encodes brief anchors', () => {
    const host = mount({
      ...waiting,
      image_reason: '<img src=x onerror=alert(1)>',
      image_brief_slug: 'x" onmouseover="alert(1)',
    });
    expect(host.querySelector('img')).toBeNull();
    expect(host.querySelector('a')?.getAttribute('onmouseover')).toBeNull();
    expect(host.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});
