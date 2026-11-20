// Renders math to standalone SVG with MathJax.
// stdin:  JSON array of {id, mml?, tex?, display}
// stdout: JSON object {id: svgString | null}
// MathML (already macro-expanded by LaTeXML) is tried first; TeX is the fallback.
const {mathjax} = require('mathjax-full/js/mathjax.js');
const {TeX} = require('mathjax-full/js/input/tex.js');
const {MathML} = require('mathjax-full/js/input/mathml.js');
const {SVG} = require('mathjax-full/js/output/svg.js');
const {liteAdaptor} = require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler} = require('mathjax-full/js/handlers/html.js');
const {AllPackages} = require('mathjax-full/js/input/tex/AllPackages.js');

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const mmlDoc = mathjax.document('', {InputJax: new MathML(), OutputJax: new SVG({fontCache: 'none'})});
const texDoc = mathjax.document('', {
  InputJax: new TeX({packages: AllPackages.filter(p => p !== 'bussproofs')}),
  OutputJax: new SVG({fontCache: 'none'}),
});

function render(doc, src, display) {
  try {
    const svg = adaptor.innerHTML(doc.convert(src, {display}));
    return svg.includes('data-mjx-error') || svg.includes('merror') || svg.includes('fill="red"') ? null : svg;
  } catch (e) {
    return null;
  }
}

let data = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', c => (data += c));
process.stdin.on('end', () => {
  const out = {};
  for (const item of JSON.parse(data)) {
    const display = !!item.display;
    let svg = null;
    if (item.mml) svg = render(mmlDoc, item.mml, display);
    if (!svg && item.tex) svg = render(texDoc, item.tex, display);
    out[item.id] = svg;
  }
  process.stdout.write(JSON.stringify(out));
});
