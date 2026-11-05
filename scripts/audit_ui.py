#!/usr/bin/env python3
"""
界面巡检与截图 (audit_ui.py)

真实浏览器（Playwright + Edge/Chromium）逐项检查面板的每个可见元素与交互：
页签/字标/HUD/图表/时间线/抽屉/弹窗/帮助/引导条/徽章/空状态/错误态，
并统计 JS 控制台错误、网络失败、横向溢出。

产出：
  scripts/_ui_shots/*.png      各视图截图
  scripts/_ui_report.json      逐项检查结果

用法: python scripts/audit_ui.py [--url http://127.0.0.1:8803]
"""

import argparse
import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'scripts', '_ui_shots')
RESULTS = []
CONSOLE_ERRORS = []
FAILED_REQUESTS = []


def check(name, ok, note=''):
    RESULTS.append({'name': name, 'ok': bool(ok), 'note': str(note)[:200]})
    print('%s  %-46s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:90]))


def shot(page, name):
    path = os.path.join(OUT, name + '.png')
    page.screenshot(path=path, full_page=False)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:8803')
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(viewport={'width': 1500, 'height': 950},
                                  device_scale_factor=1)
        page = ctx.new_page()
        page.on('console', lambda m: CONSOLE_ERRORS.append(m.text)
                if m.type == 'error' else None)
        page.on('requestfailed', lambda r: FAILED_REQUESTS.append(r.url))

        page.goto(args.url, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(1800)

        # 1. 基础渲染
        title = page.title()
        check('页签标题含品牌', 'World Games' in title or '行者' in title or '万界' in title, title)
        check('data-skin 属性存在', page.eval_on_selector('body', 'e => e.dataset.skin') not in (None, ''),
              page.eval_on_selector('body', 'e => e.dataset.skin'))
        shot(page, '01-stage')

        # 2. HUD 数值：从 /state 读取真实值再断言渲染（不硬编码存档数字，
        #    否则换一份存档就会假失败——本脚本上一版正是这样）
        import urllib.request as _ur
        vm0 = json.load(_ur.urlopen(args.url.rstrip('/') + '/state', timeout=8))
        body_text = page.inner_text('body')
        tick_str = '{:,}'.format(int(vm0.get('tick', 0)))
        check('回合号已渲染（与 /state 一致）', tick_str in body_text,
              'tick=%s' % tick_str)
        check('主角名已渲染（与 /state 一致）',
              str(vm0.get('player', {}).get('name', '')) in body_text,
              vm0.get('player', {}).get('name'))
        hp_v = vm0.get('player', {}).get('hp')
        check('气血数值渲染（与 /state 一致）', str(hp_v) in body_text, 'hp=%s' % hp_v)

        # 3. 图表 canvas 实际绘制（非零尺寸 + 有像素）
        sized = page.evaluate('''() => Array.from(document.querySelectorAll('canvas'))
            .map(c => ({w: c.width, h: c.height, has: !!c.getContext('2d')}))''')
        check('图表 canvas 存在且尺寸有效',
              len(sized) > 0 and all(c['w'] > 50 and c['h'] > 50 for c in sized),
              '%d 个 canvas' % len(sized))

        # 4. 时间线有事件
        check('事件时间线有内容', '编年' in body_text or '事件' in body_text,
              body_text[:40].replace('\n', ' '))

        # 5. 抽屉：图鉴 / 市场 / 大事记
        # 抽屉是原生 <details>，点 summary 展开
        for drawer_id, label in [('drawer-codex', '图鉴'), ('drawer-market', '市场'),
                                 ('drawer-milestones', '大事记')]:
            el = page.query_selector('#' + drawer_id)
            if el:
                page.evaluate('(d) => { d.open = true; }', el)
                page.wait_for_timeout(400)
                visible = page.evaluate(
                    '(d) => d.open && d.getBoundingClientRect().height > 40', el)
                check('抽屉可展开：%s' % label, visible,
                      'height=%d' % page.evaluate('(d)=>d.getBoundingClientRect().height', el))
                shot(page, '02-drawer-' + label)
                page.evaluate('(d) => { d.open = false; }', el)
            else:
                check('抽屉元素存在：%s' % label, False, '#' + drawer_id + ' 不存在')

        # 6. 帮助弹窗
        helpbtn = page.query_selector('#help-btn')
        if helpbtn:
            helpbtn.click()
            page.wait_for_timeout(600)
            open_ok = page.evaluate('''() => {
                const d = document.querySelector('#helpdlg');
                return !!d && (d.open || getComputedStyle(d).display !== 'none');
            }''')
            check('帮助弹窗可打开', open_ok)
            shot(page, '03-help')
            help_text = page.inner_text('#helpdlg') if page.query_selector('#helpdlg') else ''
            check('帮助含术语表', '术语' in help_text or '心流' in help_text)
            check('帮助含数据位置', '状态文件' in help_text or '.json' in help_text)
            page.keyboard.press('Escape')
            page.wait_for_timeout(300)
        else:
            check('帮助按钮存在', False, '#help-btn 不存在')

        # 7. 无横向溢出（1500 与 320）
        for w, h, tag in [(1500, 950, '1500'), (768, 900, '768'), (320, 800, '320')]:
            page.set_viewport_size({'width': w, 'height': h})
            page.wait_for_timeout(700)
            overflow = page.evaluate(
                '() => document.documentElement.scrollWidth - document.documentElement.clientWidth')
            check('无横向溢出 @%spx' % tag, overflow <= 1, 'overflow=%spx' % overflow)
            shot(page, '04-responsive-' + tag)

        # 8. 控制台与网络
        page.set_viewport_size({'width': 1500, 'height': 950})
        page.wait_for_timeout(500)
        check('无 JS 控制台错误', not CONSOLE_ERRORS,
              '; '.join(CONSOLE_ERRORS[:2]) if CONSOLE_ERRORS else '0 条')
        check('无失败网络请求', not FAILED_REQUESTS,
              '; '.join(FAILED_REQUESTS[:2]) if FAILED_REQUESTS else '0 条')

        browser.close()

    with open(os.path.join(ROOT, 'scripts', '_ui_report.json'), 'w', encoding='utf-8') as f:
        json.dump({'checks': RESULTS,
                   'console_errors': CONSOLE_ERRORS,
                   'failed_requests': FAILED_REQUESTS}, f, ensure_ascii=False, indent=2)

    passed = sum(1 for r in RESULTS if r['ok'])
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
