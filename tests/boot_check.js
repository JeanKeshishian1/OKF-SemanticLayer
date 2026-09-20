// Boot every <script> of one rendered page against a stub DOM, in order, in
// one shared context - the way a browser runs classic scripts. Exit 1 on a
// syntax error, a synchronous throw, or an unhandled rejection.
//
// Why: the page serves two faces from one file and splits its script into a
// shared part and a per-face part. A top-level statement that touches an
// element the other face does not have (e.g. `$('search').addEventListener`
// on the end-user page) throws at boot and takes every later statement with
// it - a blank, silent page. No browser is needed to catch that: element
// lookups here answer like a real DOM would - a permissive stub for an id
// the page actually contains, null for one it does not - so only genuinely
// broken boot code fails. Run by tests/test_demo.py for each face; by hand:
//     node tests/boot_check.js rendered.html
'use strict';
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (!scripts.length) { console.error('no <script> blocks found'); process.exit(1); }
const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));

// A stub that tolerates any property read, call, assignment or iteration:
// enough for listeners to be attached, innerHTML to be set, classList to
// be toggled and querySelectorAll results to be spread into empty arrays.
function stub() {
  return new Proxy(function () {}, {
    get(_t, prop) {
      if (prop === 'then') return undefined;               // never thenable
      if (prop === Symbol.iterator) return function* () {}; // spreads to []
      if (prop === Symbol.toPrimitive) return () => 0;      // arithmetic stays finite
      return stub();
    },
    apply() { return stub(); },
    set() { return true; },
  });
}

// The document answers id lookups from the served markup; everything else
// is permissive.
const document = new Proxy(stub(), {
  get(target, prop) {
    if (prop === 'getElementById') return id => (ids.has(String(id)) ? stub() : null);
    return target[prop];
  },
});

const failures = [];
const context = vm.createContext({
  document, window: stub(), navigator: stub(), localStorage: stub(),
  matchMedia: () => stub(), requestAnimationFrame: fn => setTimeout(fn, 0),
  setTimeout, clearTimeout, console, TextDecoder, TextEncoder, AbortController,
  URL, URLSearchParams, Promise, JSON, Math, Date, Number, String, Array, Object,
  Map, Set, Symbol, Error, RegExp,
  // The network never answers: every loader must take its own error path
  // without throwing out of the boot sequence.
  fetch: () => Promise.reject(new Error('offline in boot check')),
});
context.globalThis = context;
process.on('unhandledRejection', reason => failures.push('unhandled rejection: ' + (reason && reason.stack || reason)));

scripts.forEach((source, index) => {
  try {
    new vm.Script(source, {filename: `script-${index}.js`}).runInContext(context);
  } catch (error) {
    failures.push(`script ${index} threw at boot: ${error.stack || error}`);
  }
});

// Let the rejected fetches settle and their catch paths run.
setTimeout(() => {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  console.log(`${scripts.length} script(s) booted cleanly against ${ids.size} ids`);
}, 50);
