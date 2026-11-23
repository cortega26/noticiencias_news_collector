import { runInThisContext } from 'node:vm';
import ts from 'typescript';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import pageSource from '../pages/triage.astro?raw';
import * as publishProgress from './publishProgress';
import * as publishWaiting from './publishWaiting';

const script = pageSource.split('<script>')[1].split('</script>')[0];
const markup = pageSource.split('<AuthGate>')[1].split('</AuthGate>')[0];
// Execute the actual page script against a DOM and a simulated API.
const mount = runInThisContext(
  `(function (require, exports) {
    ${
      ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
    }
  })`,
  { filename: 'triage.astro:test-script' }
);

function article(id: number, title = `Article ${id}`) {
  return {
    id,
    title,
    url: 'https://example.org/article',
    source: { name: 'Source' },
    topics: [],
    why_ranked: [],
    processing_status: 'validated',
    publishable: true,
  };
}

function page(data: ReturnType<typeof article>[], next_cursor: string | null = null) {
  return { data, pagination: { next_cursor, has_more: next_cursor !== null } };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

const api = {
  listArticles: vi.fn(),
  getArticle: vi.fn(),
  updateAuditStatus: vi.fn(),
  rejectArticle: vi.fn(),
  clearToken: vi.fn(),
  showAuthGate: vi.fn(() => document.getElementById('auth-gate')?.classList.remove('hidden')),
  startPublish: vi.fn(),
};

function start() {
  mount((name: string) => {
    if (name === '../lib/api') return api;
    if (name === '../lib/publishProgress') return publishProgress;
    if (name === '../lib/publishWaiting') return publishWaiting;
    throw new Error(`Unexpected script import: ${name}`);
  }, {});
}

function click(selector: string) {
  document.querySelector<HTMLButtonElement>(selector)!.click();
}

function key(key: string, init: KeyboardEventInit = {}, target: EventTarget = document) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

const detail = () => document.getElementById('detail')!;
const queue = () => document.getElementById('queue')!;

describe('Triage selection and queue identity', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.spyOn(window, 'addEventListener');
    vi.spyOn(document, 'addEventListener');
    window.sessionStorage.clear();
    document.body.innerHTML = `<div id="auth-gate" class="hidden"></div>${markup}`;
    api.listArticles.mockResolvedValue(page([article(1), article(2)]));
    api.getArticle.mockImplementation(async (id: number) => article(id));
    api.updateAuditStatus.mockResolvedValue({ status: 'ok', detail: 'Audit saved' });
  });

  afterEach(() => {
    for (const [event, listener] of vi.mocked(document.addEventListener).mock.calls) {
      document.removeEventListener(event, listener);
    }
    for (const [event, listener] of vi.mocked(window.addEventListener).mock.calls) {
      window.removeEventListener(event, listener);
    }
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it('blocks stale buttons and shortcuts while a new detail is pending or failed', async () => {
    const second = deferred<ReturnType<typeof article>>();
    api.getArticle.mockImplementation(async (id: number) =>
      id === 2 ? second.promise : article(1)
    );
    start();
    await vi.waitFor(() => expect(detail().textContent).toContain('Article 1'));
    const oldButton = detail().querySelector<HTMLButtonElement>('[data-action="audit-pass"]')!;
    click('[data-id="2"]');
    expect(detail().textContent).toContain('Cargando');
    expect(detail().querySelector('[data-action]')).toBeNull();
    oldButton.click();
    key('a');
    key('r');
    key('p');
    second.reject(new Error('fixture failure'));
    await vi.waitFor(() => expect(detail().textContent).toContain('No se pudo cargar'));
    key('a');
    expect(api.updateAuditStatus).not.toHaveBeenCalled();
    expect(api.rejectArticle).not.toHaveBeenCalled();
    expect(api.startPublish).not.toHaveBeenCalled();
  });

  it('discards older results even when the same article is selected again', async () => {
    const old = deferred<ReturnType<typeof article>>();
    api.getArticle.mockReturnValueOnce(old.promise);
    start();
    await vi.waitFor(() => expect(api.getArticle).toHaveBeenCalledWith(1));
    click('[data-id="2"]');
    click('[data-id="1"]');
    await vi.waitFor(() => expect(detail().textContent).toContain('Article 1'));
    old.resolve(article(1, 'Stale title'));
    await old.promise;
    expect(detail().textContent).not.toContain('Stale title');
  });

  it('ignores stale mutation results and performs a valid action on the active article', async () => {
    const audit = deferred<{ status: string; detail: string }>();
    api.updateAuditStatus.mockReturnValueOnce(audit.promise);
    start();
    await vi.waitFor(() => expect(detail().textContent).toContain('Article 1'));
    key('a');
    expect(api.updateAuditStatus).toHaveBeenCalledWith(1, 'passed');
    click('[data-id="2"]');
    await vi.waitFor(() => expect(detail().textContent).toContain('Article 2'));
    audit.resolve({ status: 'ok', detail: 'Stale audit' });
    await audit.promise;
    expect(detail().textContent).not.toContain('passed');
    expect(document.getElementById('toast')?.textContent).not.toContain('Stale audit');
    click('[data-action="audit-fail"]');
    expect(api.updateAuditStatus).toHaveBeenLastCalledWith(2, 'failed');
  });

  it('adopts only the latest filter and deduplicates concurrent requests for its cursor', async () => {
    const old = deferred<ReturnType<typeof page>>();
    const more = deferred<ReturnType<typeof page>>();
    api.listArticles
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(page([article(2)], 'rejected-next'))
      .mockReturnValueOnce(more.promise);
    start();
    Array.from(document.querySelectorAll<HTMLButtonElement>('#status-filter button'))
      .find((button) => button.textContent === 'Rechazados')!
      .click();
    await vi.waitFor(() => expect(queue().textContent).toContain('Article 2'));
    old.resolve(page([article(1)], 'ready-next'));
    await old.promise;
    expect(queue().textContent).not.toContain('Article 1');
    click('#load-more');
    click('#load-more');
    expect(api.listArticles.mock.calls).toEqual([
      ['publishable', null, 20],
      ['rejected', null, 20],
      ['rejected', 'rejected-next', 20],
    ]);
    more.resolve(page([article(3)]));
    await vi.waitFor(() => expect(queue().querySelectorAll('[data-id="3"]')).toHaveLength(1));
  });

  it('reloads on first login and ignores shortcuts while gated, editing, or modified', async () => {
    const gate = document.getElementById('auth-gate')!;
    api.listArticles.mockRejectedValueOnce(
      Object.assign(new Error('Login'), { name: 'AuthError' })
    );
    start();
    await vi.waitFor(() => expect(gate.classList.contains('hidden')).toBe(false));
    gate.classList.add('hidden');
    window.dispatchEvent(new CustomEvent('auth:ready'));
    await vi.waitFor(() => expect(detail().textContent).toContain('Article 1'));
    for (const init of [
      { metaKey: true },
      { ctrlKey: true },
      { altKey: true },
      { shiftKey: true },
      { repeat: true },
    ]) {
      expect(key('a', init).defaultPrevented).toBe(false);
    }
    const editor = document.createElement('div');
    editor.contentEditable = 'true';
    document.body.appendChild(editor);
    key('a', {}, editor);
    gate.classList.remove('hidden');
    key('a');
    click('[data-action="audit-pass"]');
    expect(api.updateAuditStatus).not.toHaveBeenCalled();
    expect(api.listArticles).toHaveBeenCalledTimes(2);
  });
});
