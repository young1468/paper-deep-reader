"""Bounded reading batches and conflict-checked field updates; no model/API calls."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import audit

CONTENT_FIELDS = {'translation', 'explanation', 'analysis', 'terms', 'detail_note'}
PLACEHOLDER = re.compile(r'TODO|TBD|待翻译|待补充|待解读', re.I)


def filled(value):
    return isinstance(value, str) and bool(value.strip()) and not PLACEHOLDER.fullmatch(value.strip())


def prose(data):
    return [(s, p) for s in data['parts'] for p in s['paragraphs'] if p['kind'] == 'paragraph']


def draft_ready(p):
    analysis = p.get('analysis', [])
    return (isinstance(analysis, list) and all(isinstance(x, dict) for x in analysis)
            and filled(p.get('translation')) and filled(p.get('explanation'))
            and (len(analysis) >= 2 or filled(p.get('detail_note')))
            and any(x.get('basis') == 'author' and x.get('evidence') for x in analysis)
            and all(filled(x.get('label')) and filled(x.get('text')) and x.get('basis') in audit.BASES for x in analysis))


def review_current(p, glossary):
    return not audit.review_errors(p, glossary)[0]


def status(data):
    sections = []
    totals = dict(paragraphs=0, draft_pending=0, review_pending=0, reviewed=0, needs_check=0)
    for s in data['parts']:
        row = {'id': s['id'], 'title': s.get('title_zh') or s['title'],
               'draft_pending': [], 'review_pending': [], 'reference_units': 0}
        for p in s['paragraphs']:
            if p['kind'] != 'paragraph':
                row['reference_units'] += 1
                continue
            totals['paragraphs'] += 1
            if not draft_ready(p):
                row['draft_pending'].append(p['id']); totals['draft_pending'] += 1
            elif not review_current(p, data['glossary']):
                row['review_pending'].append(p['id']); totals['review_pending'] += 1
            else:
                totals[p['review']['status']] += 1
        sections.append(row)
    return {'title': data['title'], 'counts': totals, 'parts': sections,
            'visuals': len(data.get('visuals', [])),
            'missing_research_card_fields': [k for k in audit.CARD_FIELDS if not data.get('research_card', {}).get(k)],
            'note': '进度只用于分批；完整结构、原文覆盖、资源、引文及审校仍由 render.py 验收。needs_check 已审校但仍有疑点，不会每次自动重发。'}


def relevant_glossary(data, selected):
    text = ' '.join(audit.original_text(p, True) for _, p in selected)
    linked = {t for _, p in selected for t in p.get('terms', [])}
    return [t for t in data['glossary'] if t['id'] in linked or any(
        re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', text, re.I)
        for word in [t['term']] + t.get('aliases_en', []))]


def batch_packet(data, selected, stage):
    guides = {s['id']: {'title': s.get('title_zh') or s['title'], 'guide': s.get('guide', '')} for s, _ in selected}
    rows = []
    for s, p in selected:
        keys = ('original', 'protected', 'pages', 'translation', 'explanation', 'analysis', 'terms', 'detail_note')
        row = {'id': p['id'], 'part_id': s['id'], 'base_digest': audit.digest(p),
               **{k: p[k] for k in keys if k in p}}
        if stage == 'review':
            row['flags'] = audit.flags_for(p, data['glossary'])
            row['previous_review'] = p.get('review', {})
        rows.append(row)
    # Include only boundary neighbours; their text is context, never an update target.
    all_prose = prose(data)
    positions = [i for i, (_, p) in enumerate(all_prose) if p['id'] in {x['id'] for x in rows}]
    neighbours = []
    if positions:
        for i in (min(positions) - 1, max(positions) + 1):
            if 0 <= i < len(all_prose):
                _, p = all_prose[i]
                neighbours.append({'id': p['id'], 'original': audit.original_text(p, True),
                                   'translation': p.get('translation', '')})
    return {'stage': stage, 'document_digest': audit.digest(data['source']),
            'glossary_digest': audit.digest(data['glossary']),
            'context': {'title': data['title'], 'research_focus': data.get('research_focus', ''),
                        'parts': guides, 'glossary': relevant_glossary(data, selected),
                        'boundary_neighbours': neighbours},
            'paragraphs': rows}


def export_batch(data, stage, ids=None, part=None, limit=12, max_chars=24000):
    if limit < 1 or max_chars < 1:
        raise ValueError('limit 和 max-chars 必须为正数。')
    candidates = prose(data)
    known_ids = {p['id'] for _, p in candidates}
    if ids is not None and not set(ids) <= known_ids:
        raise ValueError('未知叙述段 ID：' + ', '.join(sorted(set(ids) - known_ids)))
    if part and part not in {s['id'] for s in data['parts']}:
        raise ValueError('未知 Part：' + part)
    eligible = []
    for s, p in candidates:
        if part and s['id'] != part:
            continue
        if ids is not None:
            if p['id'] not in ids:
                continue
        elif stage == 'draft' and draft_ready(p):
            continue
        elif stage == 'review' and (not draft_ready(p) or review_current(p, data['glossary'])):
            continue
        if stage == 'review' and not draft_ready(p):
            raise ValueError(p['id'] + ' 首轮内容尚未完成，不能提前审校。')
        eligible.append((s, p))
    selected = []
    packet = batch_packet(data, selected, stage)
    def selection(count):
        return {'selected': count, 'remaining': len(eligible) - count,
                'budget_chars': max_chars, 'oversize_single_paragraph': False}
    for item in eligible[:limit]:
        trial = batch_packet(data, selected + [item], stage)
        trial['selection'] = selection(len(selected) + 1)
        size = len(json.dumps(trial, ensure_ascii=False, separators=(',', ':')))
        if selected and size > max_chars:
            break
        selected.append(item); packet = trial
    packet['selection'] = selection(len(selected))
    packet['selection']['oversize_single_paragraph'] = (len(selected) == 1 and
        len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))) > max_chars)
    return packet


def apply_updates(data, patch):
    stage = patch.get('stage')
    if stage not in ('draft', 'review'):
        raise ValueError('补丁 stage 必须为 draft 或 review。')
    if patch.get('document_digest') != audit.digest(data['source']):
        raise ValueError('原文版本不匹配，未应用补丁。')
    if patch.get('glossary_digest') != audit.digest(data['glossary']):
        raise ValueError('术语表已改变；重新导出并核对术语，未应用补丁。')
    result = copy.deepcopy(data)
    idx = {p['id']: p for _, p in prose(result)}
    updates = patch.get('updates')
    if not isinstance(updates, list) or not updates:
        raise ValueError('updates 必须为非空列表。')
    seen = set()
    for update in updates:
        pid = update['id']
        if pid not in idx or pid in seen:
            raise ValueError('未知或重复的段落：' + pid)
        seen.add(pid); p = idx[pid]
        if update.get('base_digest') != audit.digest(p):
            raise ValueError(pid + ' 内容已变化；重新导出该段，未应用补丁。')
        fields = update.get('set', {})
        allowed = CONTENT_FIELDS | ({'review'} if stage == 'review' else set())
        if not isinstance(fields, dict) or not fields or not set(fields) <= allowed:
            raise ValueError(pid + ' 只能更新内容字段；不能修改原文、来源、结构或保护标记。')
        before = p.get('translation')
        p.update(copy.deepcopy(fields))
        if not draft_ready(p):
            raise ValueError(pid + ' 首轮内容不完整；请补充译文、直觉说明和分层解读。')
        if stage == 'review':
            if 'review' not in fields or not isinstance(p['review'], dict):
                raise ValueError(pid + ' 缺实际第二轮审校记录。')
            # The model authors the findings; the script binds them to exactly this version.
            p['review']['digest'] = audit.review_digest(p, result['glossary'])
            if p.get('translation') != before and not any(
                    x.get('before') and x['before'] in before and x.get('after') and x['after'] in p['translation']
                    for x in p['review'].get('changes', [])):
                raise ValueError(pid + ' 修改译文时须记录真实修订前后片段及原因。')
            errors, _, _ = audit.review_errors(p, result['glossary'])
            if errors:
                raise ValueError('\n'.join(errors))
    return result


def atomic_save(path, data, original):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.reading-', suffix='.tmp', delete=False) as f:
            temporary = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        if path.read_bytes() != original:
            raise ValueError('reading.json 在写回前发生变化，未覆盖；请重新导出。')
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'export', 'apply'):
        command = commands.add_parser(name)
        command.add_argument('input', type=Path)
        if name == 'export':
            command.add_argument('--stage', choices=('draft', 'review'), required=True)
            command.add_argument('--part')
            command.add_argument('--ids', help='Comma-separated paragraph IDs; explicitly reopen completed paragraphs.')
            command.add_argument('--limit', type=int, default=12)
            command.add_argument('--max-chars', type=int, default=24000)
            command.add_argument('--out', type=Path, required=True)
        if name == 'apply':
            command.add_argument('patch', type=Path)
    args = parser.parse_args()
    try:
        original = args.input.read_bytes()
        data = json.loads(original)
        if data.get('schema_version') != 2:
            raise ValueError('分批工具用于 v2；旧包先按内容格式升级，原渲染器仍兼容 v1。')
        if args.command == 'status':
            output = status(data)
        elif args.command == 'export':
            protected = {args.input.resolve(), (args.input.parent / 'source.json').resolve(),
                         (args.input.parent / data['source']['file']).resolve()}
            if args.out.resolve() in protected:
                raise ValueError('工作批次不能覆盖阅读数据、source.json 或原文文件。')
            packet = export_batch(data, args.stage, args.ids.split(',') if args.ids is not None else None,
                                  args.part, args.limit, args.max_chars)
            args.out.write_text(json.dumps(packet, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            output = {'batch': str(args.out.resolve()), 'stage': args.stage, **packet['selection'],
                      'note': '只读取此批文件；完整段落从不截断。'}
        else:
            if args.input.name == 'source.json':
                raise ValueError('source.json 为不可改的提取基线，不能应用内容补丁。')
            patch = json.loads(args.patch.read_text(encoding='utf-8'))
            updated = apply_updates(data, patch)
            atomic_save(args.input, updated, original)
            output = {'applied': [p['id'] for p in patch['updates']], 'stage': patch['stage']}
        print(json.dumps(output, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, '未完成操作：' + str(exc) + '\n')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
