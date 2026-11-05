#!/usr/bin/env python3
"""Panel internationalisation self-check (verify_i18n.py)

Why this exists: the panel is the product's only visible surface, and the
English README shows it. A panel that only speaks Chinese makes the bilingual
claim false. This check keeps the translation layer honest:

  I1  panel.i18n.js exposes the expected API and defaults to English
  I2  every dictionary key is unique (a duplicate silently shadows an entry)
  I3  every template has a unique placeholder name set (repeat names cannot be
      substituted unambiguously and would leak half-translated text)
  I4  the output side of every template is free of CJK
  I5  the panel page loads the translator before panel.js and offers both buttons
  I6  the server whitelists /panel.i18n.js with a JavaScript MIME type
  I7  the dictionary has no no-op identity mappings
  I8  the render pipeline actually calls the translator

Usage:  python scripts/verify_i18n.py
Exit:   0 = consistent, 1 = defect
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = []

CJK = re.compile(r'[\u4e00-\u9fff]')


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-58s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:90]))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


def main():
    src = read('panel.i18n.js')

    # I1 API and default language
    check('I1a translator exposes translateDom/setLang/detect',
          all(token in src for token in ('translateDom', 'setLang', 'detect')))
    check('I1b default language is English',
          re.search(r'var current = "en";', src) is not None)

    # I2 dictionary keys must be unique
    block = src.split('var EN = {', 1)[1].split('\n  };', 1)[0]
    keys = []
    for line in block.splitlines():
        match = re.match(r'^\s{4}"(.*)":\s', line)
        if match:
            keys.append(match.group(1))
    dupes = sorted({key for key in keys if keys.count(key) > 1})
    check('I2 dictionary keys are unique', not dupes, str(dupes[:5]))

    # I3/I4 template sanity
    tpl_block = src.split('var EN_TEMPLATES = [', 1)[1].split('\n  ];', 1)[0]
    pairs = []
    for line in tpl_block.splitlines():
        match = re.match(r'^\s{4}\["(.*?)",\s*"(.*?)"\]', line)
        if match:
            pairs.append((match.group(1), match.group(2)))
    repeated = [p for p, _ in pairs
                if len(re.findall(r'\{\w+\}', p)) != len(set(re.findall(r'\{\w+\}', p)))]
    cjk_out = [p for p, out in pairs if CJK.search(out)]
    check('I3a templates parse', len(pairs) > 40, '%d templates' % len(pairs))
    check('I3b no template repeats a placeholder name', not repeated, str(repeated[:3]))
    check('I4 no template output contains CJK', not cjk_out, str(cjk_out[:3]))

    # I7 no identity mappings
    identity = []
    for line in block.splitlines():
        match = re.match(r'^\s{4}"(.*?)":\s*"(.*?)",?\s*$', line)
        if match and match.group(1) == match.group(2):
            identity.append(match.group(1))
    check('I7 dictionary has no no-op identity mappings', not identity, str(identity[:5]))

    # I5 page wiring
    html = read('panel.html')
    ordered = ('panel.i18n.js' in html and '/panel.js' in html
               and html.index('panel.i18n.js') < html.index('/panel.js'))
    check('I5a page loads the translator before panel.js', ordered)
    check('I5b page offers both language buttons',
          'data-set-panel-lang="en"' in html and 'data-set-panel-lang="zh"' in html)

    # I6 server whitelist
    panel_py = read('panel.py')
    check('I6a server whitelists /panel.i18n.js', '"/panel.i18n.js"' in panel_py)
    check('I6b served with a JavaScript MIME type',
          re.search(r'"/panel\.i18n\.js":\s*\("panel\.i18n\.js",\s*"text/javascript',
                    panel_py) is not None)

    # I8 render pipeline uses it
    js = read('panel.js')
    check('I8 render pipeline calls the translator', js.count('PanelI18n') >= 2,
          '%d call sites' % js.count('PanelI18n'))

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
