import os
import re
import csv
import difflib
import argparse

DEFAULT_OUTPUT_DIR = 'output'


def read_file(filepath):
    for enc in ('utf-8-sig', 'gb18030', 'utf-8', 'latin-1'):
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    return ''


def extract_body(content, pkg_name):
    upper = content.upper()
    pkg_upper = pkg_name.upper()
    schema_prefix = r'(?:\w+\.)?' + r'(?:"\w+"\.)?'
    pkg_ref = schema_prefix + r'(?:"?)' + re.escape(pkg_upper) + r'(?:"?)'
    pat_start = re.compile(
        r'CREATE\s+OR\s+REPLACE\s+PACKAGE\s+BODY\s+' + pkg_ref + r'\s+(?:IS|AS)\b',
        re.IGNORECASE)
    lines = content.splitlines()
    start_idx = -1
    for i, line in enumerate(lines):
        if pat_start.search(line):
            start_idx = i
            break
    if start_idx < 0:
        pat_start2 = re.compile(
            r'CREATE\s+OR\s+REPLACE\s+PACKAGE\s+BODY\s+' + pkg_ref,
            re.IGNORECASE)
        for i, line in enumerate(lines):
            if pat_start2.search(line):
                start_idx = i
                for j in range(i + 1, min(i + 5, len(lines))):
                    if re.match(r'^\s*(IS|AS)\s*$', lines[j], re.IGNORECASE):
                        break
                break
    if start_idx < 0:
        return content
    pat_end = re.compile(
        r'^\s*END\s+' + pkg_ref + r'\s*;',
        re.IGNORECASE)
    end_idx = -1
    for i in range(len(lines) - 1, start_idx, -1):
        if pat_end.match(lines[i]):
            end_idx = i
            break
    if end_idx < 0:
        for i in range(len(lines) - 1, start_idx, -1):
            s = lines[i].strip().upper()
            if s == 'END;' or s == 'END':
                end_idx = i
                break
    if end_idx < 0:
        end_idx = len(lines) - 1
    return '\n'.join(lines[start_idx:end_idx + 1])


def split_units(content):
    units = []
    lines = content.splitlines()
    n = len(lines)

    pat_sig = re.compile(
        r'^\s*(FUNCTION|PROCEDURE)\s+(\w+)\s*\(',
        re.IGNORECASE)
    pat_name_only = re.compile(
        r'^\s*(FUNCTION|PROCEDURE)\s+(\w+)\s*$',
        re.IGNORECASE)

    i = 0
    while i < n:
        m = pat_sig.match(lines[i])
        if not m:
            m = pat_name_only.match(lines[i])
            if m:
                found_paren_line = False
                for j in range(i + 1, min(i + 6, n)):
                    if '(' in lines[j]:
                        found_paren_line = True
                        break
                    s = lines[j].strip()
                    if s and not s.startswith('--'):
                        break
                if not found_paren_line:
                    i += 1
                    continue
            else:
                i += 1
                continue

        unit_type = m.group(1).upper()
        unit_name = m.group(2).upper()
        sig_start = i

        paren_depth = 0
        in_string = False
        str_ch = ''
        found_close_paren = False
        sig_end = i

        for j in range(i, n):
            line = lines[j]
            k = 0
            while k < len(line):
                c = line[k]
                if in_string:
                    if c == str_ch:
                        if c == "'" and k + 1 < len(line) and line[k + 1] == "'":
                            k += 2
                            continue
                        in_string = False
                else:
                    if c == "'":
                        in_string = True
                        str_ch = "'"
                    elif c == '"':
                        in_string = True
                        str_ch = '"'
                    elif c == '-' and k + 1 < len(line) and line[k + 1] == '-':
                        break
                    elif c == '(':
                        paren_depth += 1
                    elif c == ')':
                        paren_depth -= 1
                        if paren_depth <= 0:
                            found_close_paren = True
                            sig_end = j
                            break
                k += 1

            if found_close_paren:
                break

        if not found_close_paren:
            i += 1
            continue

        body_start = sig_end + 1
        for j in range(sig_end, min(sig_end + 10, n)):
            stripped = lines[j].strip().upper()
            if stripped in ('IS', 'AS'):
                body_start = j + 1
                break
            if re.match(r'^\s*(RETURN\s+\w+\s*)$', lines[j], re.IGNORECASE):
                body_start = j + 1
            elif re.match(r'^\s*RETURN\s+\w+\s+(IS|AS)\s*$', lines[j], re.IGNORECASE):
                body_start = j + 1
                break

        begin_depth = 0
        end_line = body_start
        found_begin = False

        for j in range(body_start, n):
            stripped = lines[j].strip().upper()
            stripped_no_comment = _strip_line_comment(stripped)

            if not stripped_no_comment:
                continue

            if re.match(r'^\s*BEGIN\b', stripped_no_comment, re.IGNORECASE):
                begin_depth += 1
                found_begin = True

            if found_begin and begin_depth > 0:
                end_pat = re.match(r'^\s*END\s*(\w*)\s*;\s*$', stripped_no_comment, re.IGNORECASE)
                if end_pat:
                    begin_depth -= 1
                    if begin_depth == 0:
                        end_line = j
                        break

        unit_lines = lines[sig_start:end_line + 1]
        units.append({
            'type': unit_type,
            'name': unit_name,
            'lines': unit_lines,
            'start': sig_start,
            'end': end_line
        })
        i = end_line + 1

    return units


def _strip_line_comment(s):
    in_str = False
    str_ch = ''
    for i, c in enumerate(s):
        if in_str:
            if c == str_ch:
                if c == "'" and i + 1 < len(s) and s[i + 1] == "'":
                    continue
                in_str = False
        else:
            if c == "'":
                in_str = True
                str_ch = "'"
            elif c == '"':
                in_str = True
                str_ch = '"'
            elif c == '-' and i + 1 < len(s) and s[i + 1] == '-':
                return s[:i].rstrip()
    return s


def preprocess_lines(lines):
    result = []
    in_block = False

    for line in lines:
        s = line.strip()

        if in_block:
            idx = s.find('*/')
            if idx >= 0:
                s = s[idx + 2:].strip()
                in_block = False
            else:
                continue

        while '/*' in s:
            si = s.find('/*')
            ei = s.find('*/', si + 2)
            if ei >= 0:
                s = (s[:si] + s[ei + 2:]).strip()
            else:
                s = s[:si].strip()
                in_block = True
                break

        if not s:
            continue
        if s.startswith('--'):
            continue

        in_str = False
        str_ch = ''
        cut = -1
        i = 0
        while i < len(s) - 1:
            c = s[i]
            if in_str:
                if c == str_ch:
                    if c == "'" and i + 1 < len(s) and s[i + 1] == "'":
                        i += 2
                        continue
                    in_str = False
            else:
                if c == "'":
                    in_str = True
                    str_ch = "'"
                elif c == '"':
                    in_str = True
                    str_ch = '"'
                elif c == '-' and s[i + 1] == '-':
                    cut = i
                    break
            i += 1

        if cut >= 0:
            s = s[:cut].rstrip()

        if not s:
            continue

        result.append(s.upper())

    return result


def normalize_whitespace_only(lines):
    preprocessed = preprocess_lines(lines)
    tokens = []
    for line in preprocessed:
        tokens.extend(re.findall(r'\w+|[^\w\s]', line))
    return tokens, '\n'.join(preprocessed)


def normalize_semantic(lines):
    preprocessed = preprocess_lines(lines)
    normalized = []
    for line in preprocessed:
        s = line
        s = re.sub(r'\bDECLARE\b', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\bEND\s+\w+\s*;', 'END;', s, flags=re.IGNORECASE)
        s = re.sub(r'\bNUMBER\b', 'NUMERIC', s, flags=re.IGNORECASE)
        s = re.sub(r'\bDEFAULT\b', ':=', s, flags=re.IGNORECASE)
        s = re.sub(r'\bNVL\b', 'COALESCE', s, flags=re.IGNORECASE)
        s = re.sub(r'\bSYSDATE\b', 'CURRENT_DATE', s, flags=re.IGNORECASE)
        s = re.sub(r'\bROWNUM\b', 'ROW_NUMBER', s, flags=re.IGNORECASE)
        s = re.sub(r'\bAS\b(?=\s*$)', 'IS', s, flags=re.IGNORECASE)
        s = re.sub(r'\bDETERMINISTIC\b', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\bRESULT_CACHE\b', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\bPARALLEL_ENABLE\b', '', s, flags=re.IGNORECASE)
        if s.strip():
            normalized.append(s.strip())
    tokens = []
    for line in normalized:
        tokens.extend(re.findall(r'\w+|[^\w\s]', line))
    return tokens, '\n'.join(normalized)


def tokenize(line):
    return re.findall(r'\w+|[^\w\s]', line)


def word_changes(old_words, new_words):
    sm = difflib.SequenceMatcher(None, old_words, new_words)
    changes = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        elif op == 'replace':
            changes += max(i2 - i1, j2 - j1)
        elif op == 'delete':
            changes += i2 - i1
        elif op == 'insert':
            changes += j2 - j1
    return changes


def compute_word_diff_tokens(old_tokens, new_tokens):
    sm = difflib.SequenceMatcher(None, old_tokens, new_tokens)
    changed_words = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        elif op == 'replace':
            changed_words += max(i2 - i1, j2 - j1)
        elif op == 'delete':
            changed_words += i2 - i1
        elif op == 'insert':
            changed_words += j2 - j1
    return len(old_tokens), len(new_tokens), changed_words


def match_units(old_units, new_units):
    old_by_name = {}
    for u in old_units:
        name = u['name']
        if name not in old_by_name:
            old_by_name[name] = []
        old_by_name[name].append(u)

    new_by_name = {}
    for u in new_units:
        name = u['name']
        if name not in new_by_name:
            new_by_name[name] = []
        new_by_name[name].append(u)

    pairs = []
    used_old = set()
    used_new = set()

    for name in old_by_name:
        if name in new_by_name:
            o_list = old_by_name[name]
            n_list = new_by_name[name]
            for idx in range(min(len(o_list), len(n_list))):
                pairs.append((o_list[idx], n_list[idx]))
                used_old.add(id(o_list[idx]))
                used_new.add(id(n_list[idx]))

    old_unmatched = [u for u in old_units if id(u) not in used_old]
    new_unmatched = [u for u in new_units if id(u) not in used_new]

    return pairs, old_unmatched, new_unmatched


def compute_scheme_diff(old_body_content, new_body_content, normalize_fn):
    old_units = split_units(old_body_content)
    new_units = split_units(new_body_content)

    pairs, old_unmatched, new_unmatched = match_units(old_units, new_units)

    total_old_words = 0
    total_new_words = 0
    total_changed_words = 0
    unit_results = []
    normalized_old_parts = []
    normalized_new_parts = []

    for old_u, new_u in pairs:
        old_tokens, old_norm = normalize_fn(old_u['lines'])
        new_tokens, new_norm = normalize_fn(new_u['lines'])
        normalized_old_parts.append(f"-- {old_u['type']} {old_u['name']}\n{' '.join(old_tokens)}")
        normalized_new_parts.append(f"-- {new_u['type']} {new_u['name']}\n{' '.join(new_tokens)}")
        ow, nw, cw = compute_word_diff_tokens(old_tokens, new_tokens)
        total_old_words += ow
        total_new_words += nw
        total_changed_words += cw
        is_changed = cw > 0
        unit_results.append({
            'name': old_u['name'],
            'type': old_u['type'],
            'old_words': ow,
            'new_words': nw,
            'changed_words': cw,
            'status': 'matched',
            'is_changed': is_changed
        })

    for u in old_unmatched:
        tokens, norm = normalize_fn(u['lines'])
        normalized_old_parts.append(f"-- {u['type']} {u['name']} [old_only]\n{' '.join(tokens)}")
        ow = len(tokens)
        total_old_words += ow
        total_changed_words += ow
        unit_results.append({
            'name': u['name'],
            'type': u['type'],
            'old_words': ow,
            'new_words': 0,
            'changed_words': ow,
            'status': 'old_only',
            'is_changed': True
        })

    for u in new_unmatched:
        tokens, norm = normalize_fn(u['lines'])
        normalized_new_parts.append(f"-- {u['type']} {u['name']} [new_only]\n{' '.join(tokens)}")
        nw = len(tokens)
        total_new_words += nw
        total_changed_words += nw
        unit_results.append({
            'name': u['name'],
            'type': u['type'],
            'old_words': 0,
            'new_words': nw,
            'changed_words': nw,
            'status': 'new_only',
            'is_changed': True
        })

    old_func_count = len(old_units)
    changed_func_count = sum(1 for u in unit_results if u['is_changed'])

    normalized_old_text = '\n\n'.join(normalized_old_parts)
    normalized_new_text = '\n\n'.join(normalized_new_parts)

    return total_old_words, total_new_words, total_changed_words, unit_results, old_func_count, changed_func_count, normalized_old_text, normalized_new_text


def extract_init_block(content, pkg_name):
    lines = content.splitlines()
    units = split_units(content)
    if not units:
        return ''
    last_unit_end = units[-1]['end']
    pkg_upper = pkg_name.upper()

    init_lines = []
    found_begin = False
    for i in range(last_unit_end + 1, len(lines)):
        s = lines[i].strip().upper()
        if not s or s.startswith('--'):
            continue
        if not found_begin:
            if s.startswith('BEGIN'):
                found_begin = True
                init_lines.append(lines[i])
            elif re.match(r'^\s*END\s+' + re.escape(pkg_upper) + r'\s*;', s):
                break
            else:
                init_lines.append(lines[i])
        else:
            init_lines.append(lines[i])
            if re.match(r'^\s*END', s):
                break

    return '\n'.join(init_lines) if init_lines else ''


def process_file(old_path, new_path, pkg_name):
    old_content = read_file(old_path)
    new_content = read_file(new_path)

    old_body = extract_body(old_content, pkg_name)
    new_body = extract_body(new_content, pkg_name)

    s1 = compute_scheme_diff(old_body, new_body, normalize_semantic)
    s2 = compute_scheme_diff(old_body, new_body, normalize_whitespace_only)

    return {
        'scheme1': s1[:4],
        'scheme2': s2[:4],
        'old_func_count1': s1[4],
        'changed_func_count1': s1[5],
        'normalized_old_s1': s1[6],
        'normalized_new_s1': s1[7],
        'old_func_count2': s2[4],
        'changed_func_count2': s2[5],
        'normalized_old_s2': s2[6],
        'normalized_new_s2': s2[7],
        'old_body': old_body,
        'new_body': new_body,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description='Compare Oracle PL/SQL package bodies with converted SQL code.'
    )
    parser.add_argument('--old', required=True, help='Directory containing original Oracle PL/SQL files.')
    parser.add_argument('--new', required=True, help='Directory containing converted SQL files.')
    parser.add_argument(
        '--output',
        default=DEFAULT_OUTPUT_DIR,
        help=f'Output directory. Defaults to {DEFAULT_OUTPUT_DIR}.'
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    dir_old = args.old
    dir_new = args.new
    output_dir = args.output
    summary_csv = os.path.join(output_dir, 'diff_summary.csv')
    detail_csv = os.path.join(output_dir, 'diff_detail.csv')

    old_files = {}
    for root, _, files in os.walk(dir_old):
        for fname in files:
            key = os.path.splitext(fname)[0].upper()
            full = os.path.join(root, fname)
            if key not in old_files:
                old_files[key] = full

    new_file_list = []
    for root, _, files in os.walk(dir_new):
        for fname in files:
            new_file_list.append(os.path.join(root, fname))

    summary_rows = [['文件名', '原始代码Word数', '新代码Word数', '变更Word数', 'Word变更比例', '原始函数/过程数', '变更函数/过程数', '变更函数/过程比例', '方案']]
    detail_rows = [['文件名', '函数/过程名', '类型', '原始Word数', '新代码Word数', '变更Word数', '变更比例', '匹配状态', '方案']]

    NORM_DIR = os.path.join(output_dir, 'normalized')
    OLD_BODY_DIR = os.path.join(output_dir, 'old_body')
    NEW_BODY_DIR = os.path.join(output_dir, 'new_body')
    os.makedirs(NORM_DIR, exist_ok=True)
    os.makedirs(OLD_BODY_DIR, exist_ok=True)
    os.makedirs(NEW_BODY_DIR, exist_ok=True)

    for new_path in sorted(new_file_list):
        new_fname = os.path.basename(new_path)
        key = os.path.splitext(new_fname)[0].upper()
        base_name = os.path.splitext(new_fname)[0]

        if key not in old_files:
            summary_rows.append([new_fname, 'NOT_FOUND', '', '', '', '', '', '', '方案1(语义归一化)'])
            summary_rows.append([new_fname, 'NOT_FOUND', '', '', '', '', '', '', '方案2(空白归一化)'])
            print(f'SKIP: {new_fname}')
            continue

        old_path = old_files[key]
        try:
            result = process_file(old_path, new_path, key)
        except Exception as e:
            print(f'ERROR: {new_fname} - {e}')
            import traceback
            traceback.print_exc()
            continue

        s1_ow, s1_nw, s1_cw, s1_units = result['scheme1']
        s2_ow, s2_nw, s2_cw, s2_units = result['scheme2']

        s1_ratio = round(s1_cw / s1_ow * 100, 2) if s1_ow > 0 else 0
        s2_ratio = round(s2_cw / s2_ow * 100, 2) if s2_ow > 0 else 0

        fc1 = result['old_func_count1']
        cc1 = result['changed_func_count1']
        fc2 = result['old_func_count2']
        cc2 = result['changed_func_count2']

        fc_ratio1 = round(cc1 / fc1 * 100, 2) if fc1 > 0 else 0
        fc_ratio2 = round(cc2 / fc2 * 100, 2) if fc2 > 0 else 0

        summary_rows.append([new_fname, s1_ow, s1_nw, s1_cw, f'{s1_ratio}%', fc1, cc1, f'{fc_ratio1}%', '方案1(语义归一化)'])
        summary_rows.append([new_fname, s2_ow, s2_nw, s2_cw, f'{s2_ratio}%', fc2, cc2, f'{fc_ratio2}%', '方案2(空白归一化)'])

        for u in s1_units:
            u_ratio = round(u['changed_words'] / u['old_words'] * 100, 2) if u['old_words'] > 0 else (0 if u['changed_words'] == 0 else 999.99)
            detail_rows.append([new_fname, u['name'], u['type'], u['old_words'], u['new_words'], u['changed_words'], f'{u_ratio}%', u['status'], '方案1(语义归一化)'])

        for u in s2_units:
            u_ratio = round(u['changed_words'] / u['old_words'] * 100, 2) if u['old_words'] > 0 else (0 if u['changed_words'] == 0 else 999.99)
            detail_rows.append([new_fname, u['name'], u['type'], u['old_words'], u['new_words'], u['changed_words'], f'{u_ratio}%', u['status'], '方案2(空白归一化)'])

        norm_prefix = os.path.join(NORM_DIR, base_name)
        with open(f'{norm_prefix}_old_s1.txt', 'w', encoding='utf-8') as f:
            f.write(result['normalized_old_s1'])
        with open(f'{norm_prefix}_new_s1.txt', 'w', encoding='utf-8') as f:
            f.write(result['normalized_new_s1'])
        with open(f'{norm_prefix}_old_s2.txt', 'w', encoding='utf-8') as f:
            f.write(result['normalized_old_s2'])
        with open(f'{norm_prefix}_new_s2.txt', 'w', encoding='utf-8') as f:
            f.write(result['normalized_new_s2'])

        with open(os.path.join(OLD_BODY_DIR, f'{base_name}_body.sql'), 'w', encoding='utf-8') as f:
            f.write(result['old_body'])

        with open(os.path.join(NEW_BODY_DIR, f'{base_name}_body.sql'), 'w', encoding='utf-8') as f:
            f.write(result['new_body'])

        print(f'Done: {new_fname} | S1: {s1_ratio}% (func {cc1}/{fc1}={fc_ratio1}%) | S2: {s2_ratio}% (func {cc2}/{fc2}={fc_ratio2}%)')

    os.makedirs(output_dir, exist_ok=True)

    with open(summary_csv, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(summary_rows)

    with open(detail_csv, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(detail_rows)

    print(f'\nSummary CSV: {summary_csv}')
    print(f'Detail CSV: {detail_csv}')
    print(f'Normalized files: {NORM_DIR}\\')
    print(f'Old body files: {OLD_BODY_DIR}\\')
    print(f'New body files: {NEW_BODY_DIR}\\')
    print(f'Total files processed: {len(new_file_list)}')


if __name__ == '__main__':
    main()
