#!/usr/bin/env python3
"""
测试自身可信度审计 (verify_tests.py)

防"假测试"：静态审计其余自检脚本里每一条断言，拒绝恒真/恒假/弱断言，
并要求每个脚本真的有足够多的断言（防止断言被删空后仍然"全绿"）。

历史上真实出现过的问题（本脚本即为防止其复发而写）：
  1. verify_cli.py 把两份 demo_state 副本互相比较，从没读被测试命令的结果；
  2. verify_panel.py 的侧写断言写成 `os.path.exists(...) or True`，永远通过；
  3. verify_panel.py 皮肤循环用 for/else 把结论硬编码成 True；
  4. stress_freeplay.py 的"回退后 stage 保持"只断言 tick >= 0，等于没测；
  5. stress_freeplay.py 的归档断言 `arch >= 0 and lines >= arch`，arch 恒 0 也过。

审计规则（AST 级，不看字符串）：
  R1 条件含字面量 True 的短路（`x or True`）
  R2 条件恒为常量 True
  R3 条件为恒真下界（`x >= 0` / `x > -1` / `0 <= x`）
  R4 名称声称"保持/不变/一致/相等"但条件只判真值（bool(x) / x / x is not None）
  R5 条件恒为常量 False（除非位于 except 处理器内——那是合法的失败记录）
  R6 断言数量不足（文件有 check/ux 定义但调用数为 0）
  R7 自反恒等式（`x == x` / `a != a`）
  R8 只判类型的弱断言（`isinstance(x, T)` 或 `x is not None` 且无值比较）
  R9 调用点位于 `if False:` 分支内（永不执行）

签名兼容：本项目有两套 check 约定——
  check(name, ok, note)        （verify_*.py）
  check(state, note, ok, detail)（stress_freeplay.py）
审计器按函数名识别参数位置，不再假定 args[1] 就是条件。

用法:  python scripts/verify_tests.py
退出码: 0 = 审计通过；1 = 发现可疑断言
"""

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 期望的断言数量下限（低于此值视为"断言被删除/清空"）
# 静态 check() 调用点数的精确基线：少一条就报 R6（删除断言/整段检查都拦得住）
EXPECTED = {
    'scripts/verify_cli.py': 9,
    'scripts/verify_panel.py': 84,
    'scripts/verify_mcp_stdio.py': 64,
    'scripts/verify_near_death.py': 7,
    'scripts/verify_formulas.py': 119,
    'scripts/verify_branches.py': 175,
    'scripts/verify_injection.py': 11,
    'scripts/verify_memory.py': 7,
    'scripts/user_playtest.py': 43,
    'scripts/stress_freeplay.py': 10,
    'scripts/verify_world.py': 48,
    'scripts/verify_settings.py': 6,
    'scripts/verify_docs.py': 22,
    'scripts/verify_gameplay.py': 45,
    'scripts/verify_generic.py': 76,
    'scripts/verify_systems.py': 90,
}
CHECK_FUNCS = {'check', 'ux', 'check_true'}
FINDINGS = []


def add(path, lineno, rule, detail, snippet):
    FINDINGS.append({'file': path, 'line': lineno, 'rule': rule,
                     'detail': detail, 'snippet': snippet.replace('\n', ' ')[:120]})


def is_const_bool(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


COMPARE_STYLE_FILES = {'scripts/verify_formulas.py'}


def cond_index(func_name, node):
    """返回条件参数在调用里的下标；本项目两套签名。"""
    if func_name == 'ux':
        return 1                      # ux(name, ok, note)
    if len(node.args) >= 3 and isinstance(node.args[1], ast.Constant) \
            and isinstance(node.args[1].value, str):
        return 2                      # check(state, note, ok, detail)
    return 1                          # check(name, ok, note)


def name_index(func_name):
    return 0


def _kw(node, *names):
    """取关键字参数的值（防 `check(name='x', ok=True)` 绕过）。"""
    for k in node.keywords:
        if k.arg in names:
            return k.value
    return None


def get_cond(func_name, node):
    """取条件表达式（含关键字传参形式）。"""
    kw = _kw(node, 'ok', 'cond', 'condition')
    if kw is not None:
        return kw
    ci = cond_index(func_name, node)
    return node.args[ci] if len(node.args) > ci else None


def get_name(func_name, node):
    """取断言名称表达式（含关键字传参形式；兼容 stress 的 (state, note, ok) 签名）。"""
    kw = _kw(node, 'name', 'note')
    if kw is not None:
        return kw
    # stress 签名：check(state_dict, 'note', cond) —— 第二个位置参数才是名字
    if func_name == 'check' and len(node.args) >= 3             and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
        return node.args[1]
    return node.args[name_index(func_name)] if len(node.args) > name_index(func_name) else None


def is_constant_expr(node):
    """整条表达式只由字面量构成（含 True if X else True / not False / len([])==0）。"""
    # IfExp 两支都为 True → 恒真；都为 False → 恒假
    if isinstance(node, ast.IfExp):
        if is_const_bool(node.body) and is_const_bool(node.orelse):
            return node.body.value == node.orelse.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)             and isinstance(node.operand, ast.Constant):
        return True
    # bool(<常量比较>) / (<常量比较>) is True|False
    # 注意：内层 1==1 由 is_self_identity 判定，这里要一并认
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)             and node.func.id == 'bool' and len(node.args) == 1:
        inner = node.args[0]
        if is_constant_expr(inner) or is_self_identity(inner):
            return True
    if isinstance(node, ast.Compare) and len(node.ops) == 1             and isinstance(node.ops[0], (ast.Is, ast.IsNot))             and isinstance(node.comparators[0], ast.Constant)             and isinstance(node.comparators[0].value, bool):
        inner = node.left
        if is_constant_expr(inner) or is_self_identity(inner):
            return True
    # 常量容器比较：len(<字面量容器>) == 常量
    if isinstance(node, ast.Compare) and len(node.ops) == 1             and isinstance(node.comparators[0], ast.Constant):
        left = node.left
        if isinstance(left, ast.Call) and isinstance(left.func, ast.Name)                 and left.func.id == 'len' and left.args                 and isinstance(left.args[0], (ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Constant)):
            return True
    return False


def is_trivial_lower_bound(node):
    """x >= 0 / x > -1 / 0 <= x —— 对非负量恒真（>= 2 这类有意义的边界不算）。"""
    if not isinstance(node, ast.Compare):
        return False
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    op, right = node.ops[0], node.comparators[0]
    if isinstance(right, ast.Constant) and isinstance(right.value, (int, float)):
        if isinstance(op, ast.GtE):
            return right.value == 0
        if isinstance(op, ast.Gt):
            return right.value == -1
    left = node.left
    if isinstance(left, ast.Constant) and isinstance(left.value, (int, float)):
        if isinstance(op, ast.LtE):
            return left.value == 0
        if isinstance(op, ast.Lt):
            return left.value == -1
    return False


def is_self_identity(node):
    """x == x / x != x 这类自反恒等式。"""
    if not isinstance(node, ast.Compare):
        return False
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    if not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
        return False
    try:
        return ast.dump(node.left) == ast.dump(node.comparators[0])
    except Exception:
        return False


def is_shape_only(node, name_node=None):
    """只判类型 / 非空 / not None，没有任何具体值比较。

    例外：断言名称本身在陈述"存在性前置条件"（如"20 个种子内至少一次"），
    这类断言用于建立前提，紧跟其后往往还有真正的值断言——不按弱断言报。
    """
    if name_node is not None and isinstance(name_node, ast.Constant) \
            and isinstance(name_node.value, str):
        if any(k in name_node.value for k in ('至少', '存在')):
            return False
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == 'isinstance':
        return True
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op, right = node.ops[0], node.comparators[0]
        if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(right, ast.Constant) \
                and right.value is None:
            return True
    return False


def has_value_comparison(node):
    """条件里是否存在真正的值比较（==/!=/</>/in）或数值字面量约束。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Compare):
            if any(isinstance(o, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
                                  ast.In, ast.NotIn)) for o in sub.ops):
                # 排除 None 比较（那是形状检查）
                if not all(isinstance(c, ast.Constant) and c.value is None
                           for c in sub.comparators):
                    return True
    return False


def has_name_claim(node):
    """名字里出现"保持/不变/一致/相等"等强断言词。"""
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and any(
        k in node.value for k in ('保持', '不变', '一致', '相等', '同一', '逐字节'))


def _is_falsey_const(expr):
    if isinstance(expr, ast.Constant):
        return not expr.value
    return False


def in_dead_branch(node, parents):
    """调用是否位于永不执行的分支内（`if False:` / `if 0:` / `while False:`）。"""
    for p in parents:
        if isinstance(p, (ast.If, ast.While)) and _is_falsey_const(p.test):
            for stmt in p.body:
                if any(n is node for n in ast.walk(stmt)):
                    return True
    return False


def in_except(node, parents):
    return any(isinstance(p, ast.ExceptHandler) for p in parents)


def audit_file(rel):
    path = os.path.join(ROOT, rel)
    src = open(path, encoding='utf-8').read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        add(rel, getattr(e, 'lineno', 0) or 0, 'R0', '文件无法解析: %s' % e, '')
        return 0

    calls = 0
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent

    def parents_of(node):
        out, cur = [], getattr(node, '_parent', None)
        while cur is not None:
            out.append(cur)
            cur = getattr(cur, '_parent', None)
        return out

    # 函数内的常量赋值表：变量名 -> 字面量表达式（用于抓 `ok = True; check(x, ok)`）
    # 按"函数作用域"建常量表：变量名相同但分属不同函数时不能互相污染。
    # 同时收录普通赋值 / 注解赋值 / 海象运算符，且"最后一次赋值"才算数
    # （`ok = True; ok = False` 的真实值是 False，不能拿首次赋值判定）。
    const_assign, mutated = {}, set()
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            continue
        assigns = {}
        for node in ast.walk(scope):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
                val = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)                     and node.value is not None:
                targets = [node.target]
                val = node.value
            elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                targets = [node.target]
                val = node.value
            for t in targets:
                assigns.setdefault(scope, {})[t.id] = val
        for name, val in (assigns.get(scope) or {}).items():
            if isinstance(val, ast.Constant):
                const_assign[(id(scope), name)] = val
            else:
                mutated.add((id(scope), name))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func.id if isinstance(node.func, ast.Name) else None
        if fname not in CHECK_FUNCS:
            continue
        calls += 1
        cond = get_cond(fname, node)
        if cond is None:
            continue
        snippet = ast.get_source_segment(src, node) or ''
        if rel in COMPARE_STYLE_FILES:
            # 对拍式：check(name, got, want)。这里只做"对拍特有"的检查，
            # 但**不能 continue**——否则 R2 恒真、R9 死分支等通用规则会全部失效，
            # 等于给审计器开后门。（上一版正是这样漏掉 check_true('x', True)。）
            got_expr = node.args[1] if len(node.args) > 1 else None
            want_expr = node.args[2] if len(node.args) > 2 else None
            if got_expr is not None and want_expr is not None:
                # 自证：两边是同一表达式（x, x）或同一字面量（1.0, 1.0）
                try:
                    if ast.dump(got_expr) == ast.dump(want_expr):
                        add(rel, node.lineno, 'R7',
                            '对拍两端是同一表达式（自证，永远相等）', snippet)
                except Exception:
                    pass
                # 期望值是"调用被测模块"取来的 → 等价于抄实现输出
                for e in (want_expr,):
                    for sub in ast.walk(e):
                        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                            base = sub.func.value
                            if isinstance(base, ast.Name) and base.id in ('M', 'C', 'SE', 'SF', 'WD', 'CE', 'SO', 'KA'):
                                add(rel, node.lineno, 'R7',
                                    '期望值调用被测实现（自证）', snippet)
                                break
            # 注意：不 continue —— 继续走下面的通用规则（含 R2 常量、R9 死分支）
        name_node = get_name(fname, node)
        snippet = ast.get_source_segment(src, node) or ''
        parents = parents_of(node)

        if in_dead_branch(node, parents):
            add(rel, node.lineno, 'R9', '调用位于 if False 分支内（永不执行）', snippet)
            continue

        for sub in ast.walk(cond):
            if isinstance(sub, ast.BoolOp):
                for v in sub.values:
                    if is_const_bool(v) and v.value is True:
                        add(rel, node.lineno, 'R1', '条件含字面量 True（短路恒真）', snippet)
                    if is_const_bool(v) and v.value is False:
                        add(rel, node.lineno, 'R5', '条件含字面量 False（短路恒假）', snippet)

        if is_const_bool(cond):
            if cond.value is True:
                add(rel, node.lineno, 'R2', '条件恒为 True', snippet)
            elif not in_except(node, parents):
                add(rel, node.lineno, 'R5', '条件恒为 False（且不在 except 内）', snippet)

        # R3：顶层或 BoolOp 里出现恒真下界（`x >= 0 and y >= 0` 同样要抓）
        lb_targets = [cond]
        for sub in ast.walk(cond):
            if isinstance(sub, ast.BoolOp):
                lb_targets.extend(sub.values)
        _is_invariant = isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)             and any(k in name_node.value for k in ('非负', '不变量', '不为小数'))
        if any(is_trivial_lower_bound(t) for t in lb_targets) and not _is_invariant:
            add(rel, node.lineno, 'R3', '条件含恒真下界（>= 0 等）', snippet)

        # 数据流：条件只是一个变量名，追到它的常量赋值
        _scope_id = None
        for p_ in parents:
            if isinstance(p_, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _scope_id = id(p_)
                break
        if _scope_id is None:
            _scope_id = id(tree)
        if isinstance(cond, ast.Name) and (_scope_id, cond.id) in const_assign                 and (_scope_id, cond.id) not in mutated:
            cv = const_assign[(_scope_id, cond.id)]
            if is_const_bool(cv) and cv.value is True:
                add(rel, node.lineno, 'R2', '条件变量 %s 被赋为常量 True（恒真）' % cond.id, snippet)
            elif isinstance(cv.value, (int, float, str)) and not isinstance(cv.value, bool):
                add(rel, node.lineno, 'R2', '条件变量 %s 被赋为裸常量（恒真）' % cond.id, snippet)

        if isinstance(cond, ast.Constant) and not isinstance(cond.value, bool):
            add(rel, node.lineno, 'R2', '条件为裸常量（非布尔值恒真）', snippet)

        if is_constant_expr(cond):
            add(rel, node.lineno, 'R2', '条件只由字面量构成（恒真/恒假）', snippet)

        if is_self_identity(cond):
            add(rel, node.lineno, 'R7', '自反恒等式（x == x）', snippet)

        if rel not in COMPARE_STYLE_FILES and has_name_claim(name_node) and not has_value_comparison(cond):
            add(rel, node.lineno, 'R4', '名称声称保持/一致，但条件无值比较', snippet)

        if is_shape_only(cond, name_node):
            add(rel, node.lineno, 'R8', '只判类型/非空/is not None，无值断言', snippet)

    # R6: 断言数量下限
    expected = EXPECTED.get(rel)
    if expected is not None and calls < expected:
        add(rel, 0, 'R6', '断言数量 %d 低于期望 %d（可能被删除/清空）' % (calls, expected), '')

    return calls


def main():
    total = 0
    for rel in EXPECTED:
        if not os.path.exists(os.path.join(ROOT, rel)):
            add(rel, 0, 'R0', '目标文件不存在', '')
            print('MISS  %s' % rel)
            continue
        n = audit_file(rel)
        total += n
        print('SCAN  %-32s %d 条断言' % (rel, n))

    print('\n审计结果：%d 条可疑断言（共审计 %d 条）' % (len(FINDINGS), total))
    for f in FINDINGS:
        print('  [%s] %s:%d  %s\n        %s'
              % (f['rule'], f['file'], f['line'], f['detail'], f['snippet']))
    if FINDINGS:
        return 1
    print('未发现恒真/恒假/弱断言。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
