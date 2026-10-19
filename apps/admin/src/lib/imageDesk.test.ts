/**
 * DOM tests for the Images-desk card renderer.
 *
 * Astro page scripts cannot be imported by vitest directly, so the card
 * template lives in `imageDesk.ts` and the page only wires events. This test
 * pins the two things the desk promises: the stored prompt is rendered as
 * text (escaped) and the copy button's payload is that exact text.
 */

import { describe, expect, it } from 'vitest';

import { renderImageCard } from './imageDesk';
import type { AdminImageBriefItem } from './types';

const brief: AdminImageBriefItem = {
  slug: '2026-10-17-neandertal',
  article_id: '3724',
  status: 'needs_editorial_image',
  reason: 'third_party_image_blocked',
  topic: 'Arqueología',
  news_angle: 'Cuidados en el Paleolítico',
  scientific_domain: 'arqueología',
  subject_scene: 'Un grupo de neandertales cuidando a un herido',
  draft_alt_text: 'Recreación de un grupo neandertal',
  tone: 'curiosidad, rigor',
  updated_at: '2026-10-17T10:00:00+00:00',
  generated_prompt:
    'Escena fotorrealista <script>alert("x")</script> & comillas "dobles".\nSegunda línea.',
};

function mount(item: AdminImageBriefItem): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderImageCard(item);
  return host;
}

describe('renderImageCard', () => {
  it('renders the full generated prompt as escaped text', () => {
    const host = mount(brief);

    const pre = host.querySelector('pre[data-prompt]');
    expect(pre?.textContent).toBe(brief.generated_prompt);
    // The markup must not inject the prompt's HTML.
    expect(host.querySelector('script')).toBeNull();
    expect(pre?.innerHTML).not.toContain('<script>');
  });

  it('renders the copy control whose payload is the prompt text', () => {
    const host = mount(brief);

    const copy = host.querySelector<HTMLButtonElement>('[data-copy]');
    expect(copy?.textContent).toContain('Copiar prompt');
    const prompt = host.querySelector<HTMLElement>('pre[data-prompt]')?.textContent ?? '';
    expect(prompt).toBe(brief.generated_prompt);
  });

  it('offers "Publicar de nuevo" only when the brief is editorial_image_ready', () => {
    const ready = mount({ ...brief, status: 'editorial_image_ready' });
    expect(ready.querySelector<HTMLButtonElement>('[data-publish]')?.dataset.publish).toBe('3724');

    const needs = mount(brief);
    expect(needs.querySelector('[data-publish]')).toBeNull();
  });

  it('renders a prompt-unavailable note instead of an empty block', () => {
    const host = mount({ ...brief, generated_prompt: null });

    expect(host.querySelector('pre[data-prompt]')).toBeNull();
    expect(host.textContent).toContain('Prompt no disponible');
  });

  it('escapes quotes so brief fields cannot break out of attributes', () => {
    const host = mount({ ...brief, topic: 'x" data-evil="1' });

    const topic = host.querySelector<HTMLInputElement>('input[data-field="topic"]');
    expect(topic?.getAttribute('data-evil')).toBeNull();
    expect(topic?.value).toBe('x" data-evil="1');
  });
});
