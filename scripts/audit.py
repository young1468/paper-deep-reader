"""Create a second-pass review packet; rule flags are clues, not semantic verdicts."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys

CHECKS = ('meaning', 'negation', 'conditions', 'numbers', 'terms', 'claims')
CARD_FIELDS = ('problem', 'contributions', 'assumptions', 'evidence', 'limitations', 'costs', 'connections')
TOKEN = re.compile(r'\[\[([MCN]\d+)\]\]')
BASES = ('author', 'analogy', 'inference', 'reader_note')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def original_text(p, include_math=False):
    def replace(m):
        ref = p.get('protected', {}).get(m[1], {})
        if not include_math and ref.get('kind') in ('math', 'citation'):
            return ''
        return ref.get('text', '')
    return TOKEN.sub(replace, p['original'])


def review_digest(p, glossary):
    # Changing either translation or its explanation invalidates the recorded review.
    fields = {k: p.get(k) for k in ('original', 'translation', 'protected', 'explanation', 'analysis', 'terms')}
    fields['glossary'] = glossary
    return digest(fields)


def numeric_facts(text):
    text = re.sub(r'(?:Fig(?:ure)?\.?|Table|Sec(?:tion)?\.?|Eq(?:uation)?\.?)\s*\d+(?:\.\d+)*', '', text, flags=re.I)
    text = TOKEN.sub('', text)
    text = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', text).replace('−', '-')
    pattern = r'(?<![A-Za-z0-9_.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?'
    values, units = set(), set()
    for m in re.finditer(pattern, text):
        value=Decimal(m.group())
        n = format(value.normalize(),'f') if value else '0'
        values.add(n)
        tail = text[m.end():].lstrip()
        for unit, regex in (
            ('pp', r'^(?:percentage points?\b|个百分点)'),
            ('%', r'^(?:%|percent\b|百分比)'),
            ('ms', r'^(?:ms\b|milliseconds?\b|毫秒)'),
            ('s', r'^(?:s\b|seconds?\b|秒)'),
            ('Hz', r'^(?:Hz\b|赫兹)'),
            ('mm', r'^(?:mm\b|millimeters?\b|毫米)'),
            ('cm', r'^(?:cm\b|centimeters?\b|厘米)'),
            ('m', r'^(?:m\b|meters?\b|米)'),
            ('kg', r'^(?:kg\b|kilograms?\b|千克|公斤)')):
            if re.search(regex, tail, re.I):
                units.add(n+' '+unit)
                break
    return values, units


def flags_for(p, glossary):
    source, target = original_text(p), p.get('translation', '')
    flags = []
    def flag(category, message, details):
        fid = 'f'+digest([p['id'], category, details])[:12]
        flags.append({'id': fid, 'category': category, 'message': message, 'details': details})
    a, au = numeric_facts(source)
    b, bu = numeric_facts(target)
    if a != b:
        flag('numbers', '原文与译文的数字集合不同，需核对数量、位置及用途。', {'source_only': sorted(a-b), 'translation_only': sorted(b-a)})
    if au != bu:
        flag('units', '单位或百分比/百分点的表达不同。', {'source_only': sorted(au-bu), 'translation_only': sorted(bu-au)})
    if re.search(r'\b(?:not|no|never|without|cannot|fails?|failed)\b', source, re.I) and not re.search(r'不|未|无|没有|难以|失败|并非|缺少', target):
        flag('negation', '原文含否定/失败表达，译文未发现常见对应词。', {})
    if re.search(r'\b(?:may|might|could|suggests?|appears? to)\b', source, re.I) and not re.search(r'可能|或许|可以|有望|提示|暗示|表明|似乎|倾向', target):
        flag('claims', '可能丢失不确定性或把谨慎主张译得过强。', {})
    if re.search(r'\b(?:if|unless|assuming|provided that|only when)\b', source, re.I) and not re.search(r'如果|若|除非|假设|只有|仅|当|条件|在', target):
        flag('conditions', '可能省略条件限定，需要逐句核对。', {})
    for term in glossary:
        english = [term['term']] + term.get('aliases_en', [])
        occurs = any(re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)', source, re.I) for t in english)
        if not occurs:
            continue
        approved = [term['translation']] + term.get('aliases_zh', []) + english
        if not any(t.casefold() in target.casefold() for t in approved):
            flag('terms', '术语未采用本篇约定译法或保留英文。', {'term': term['term'], 'approved': approved})
        bad = [t for t in term.get('avoid_zh', []) if t in target]
        if bad:
            flag('terms', '出现本篇明确排除的术语译法。', {'term': term['term'], 'found': bad})
    return flags


def evidence_errors(items, paragraphs, label):
    errors = []
    if not items:
        return [label+' 缺原文依据']
    for item in items:
        pid, quote = item.get('paragraph_id'), item.get('quote', '')
        p = paragraphs.get(pid)
        if not p:
            errors.append(label+' 的依据段落不存在：'+str(pid))
        elif not quote.strip() or re.sub(r'\s+', ' ', quote).strip() not in re.sub(r'\s+', ' ', original_text(p, True)).strip():
            errors.append(label+' 的引文不是所指原文中的连续片段')
    return errors


def needs_visual(ref):
    if 'detail_required' in ref:
        return bool(ref['detail_required'])
    text = ref.get('text','')
    return len(text)>=24 or bool(re.search(r'[=∑∫]|\\(?:frac|sum|int)',text))


def review_errors(p, glossary):
    """The same strict paragraph review checks used by the full validator and batches."""
    errors = []
    pid = p['id']
    paragraphs = {pid: p}
    review = p.get('review', {})
    current_digest = review_digest(p, glossary)
    if review.get('digest') != current_digest:
        errors.append(pid+' 审校缺失或已过期；请审校当前译文和解读')
    if review.get('method') != 'model_second_pass' or review.get('status') not in ('reviewed', 'needs_check'):
        errors.append(pid+' 缺有效的第二轮模型审校记录')
    if not all(isinstance(review.get('checklist', {}).get(k), str) and review['checklist'][k].strip()
               and not re.fullmatch(r'通过|已检查|无误|OK|checked|passed',review['checklist'][k].strip(),re.I) for k in CHECKS):
        errors.append(pid+' 审校须记录六类检查的具体结论')
    flags = flags_for(p, glossary)
    decisions = {x.get('id'): x for x in review.get('decisions', [])}
    open_flags = []
    for flag in flags:
        decision = decisions.get(flag['id'], {})
        if decision.get('resolution') not in ('accepted', 'open') or not decision.get('reason', '').strip():
            errors.append(pid+' 的规则提示尚未处理：'+flag['id'])
        if decision.get('resolution')=='open':
            open_flags.append(flag['id'])
    if open_flags and review.get('status')!='needs_check':
        errors.append(pid+' 尚有待核对问题，不能标记为已审校')
    for change in review.get('changes', []):
        if not all(change.get(k) for k in ('before','after','reason','source_quote')):
            errors.append(pid+' 修订记录缺少前后译文、原因或原文依据')
        elif change['after'] not in p['translation']:
            errors.append(pid+' 修订后的文字不在当前译文中')
        else:
            errors.extend(evidence_errors([{'paragraph_id':pid,'quote':change['source_quote']}], paragraphs, pid+' 修订'))
    return errors, flags, current_digest


def check_v2(data):
    """Check review records, evidence anchors, and enhanced reading components."""
    errors, records = [], []
    paragraphs = {p['id']: p for s in data['parts'] for p in s['paragraphs']}
    glossary = data['glossary']
    for item in data.get('overview',[]):
        if item.get('basis') not in BASES:
            errors.append('整体解读缺少归属类型 basis')
        errors.extend(evidence_errors(item.get('evidence',[]),paragraphs,'整体解读'))
    for p in paragraphs.values():
        if p['kind'] != 'paragraph':
            continue
        pid = p['id']
        analysis = p.get('analysis', [])
        if len(analysis)<2 and not p.get('detail_note', '').strip():
            errors.append(pid+' 需至少两个具体解读层次；短过渡段可用 detail_note 说明')
        if not any(x.get('basis')=='author' for x in analysis):
            errors.append(pid+' 缺关联原文的论文含义解读')
        for item in analysis:
            if not item.get('label') or not item.get('text') or item.get('basis') not in BASES:
                errors.append(pid+' 解读需含 label、text 及有效 basis')
            if item.get('basis')=='author' or item.get('evidence'):
                errors.extend(evidence_errors(item.get('evidence', []), paragraphs, pid+' 解读'))
        review = p.get('review', {})
        review_issues, flags, current_digest = review_errors(p, glossary)
        errors.extend(review_issues)
        records.append({'paragraph_id':pid, 'status':review.get('status'), 'flags':flags,
                        'review':review, 'digest':current_digest})
    visuals = data.get('visuals', [])
    visual_ids = [v.get('id') for v in visuals]
    if len(visual_ids)!=len(set(visual_ids)):
        errors.append('图表/公式解读 ID 重复')
    covered = set()
    for v in visuals:
        label = str(v.get('id'))
        if v.get('kind') not in ('formula','figure','table') or not v.get('title') or not v.get('summary'):
            errors.append(label+' 图表/公式解读缺类型、标题或概述')
        required = {'formula':{'purpose','symbols','mechanism','boundary'},
                    'figure':{'axes','setup','observations','boundary'},
                    'table':{'headers','setup','observations','boundary'}}.get(v.get('kind'),set())
        if not required<={x.get('role') for x in v.get('details', [])} or any(not x.get('label') or not x.get('text') for x in v.get('details', [])):
            errors.append(label+' 图表/公式解读缺少所需的具体说明层次')
        errors.extend(evidence_errors(v.get('evidence', []), paragraphs, label))
        if not v.get('paragraph_ids') or not set(v['paragraph_ids'])<=set(paragraphs):
            errors.append(label+' 关联段落无效')
        for pid in v.get('paragraph_ids', []):
            key = v.get('protected_key')
            if key:
                if paragraphs.get(pid, {}).get('protected', {}).get(key, {}).get('kind')!='math':
                    errors.append(label+' 关联的数学标记不存在')
                covered.add((pid,key))
            else:
                covered.add((pid,'visual'))
    for p in paragraphs.values():
        for key, ref in p.get('protected', {}).items():
            if ref['kind']=='math' and needs_visual(ref) and (p['id'],key) not in covered:
                errors.append(p['id']+' 的 '+key+' 缺公式解读')
        if p.get('visual_kind') and (p['id'],'visual') not in covered:
            errors.append(p['id']+' 缺图表/独立公式解读')
    card = data.get('research_card', {})
    for field in CARD_FIELDS:
        items = card.get(field, [])
        if not items:
            errors.append('科研阅读卡片缺 '+field)
        for item in items:
            if not item.get('text') or item.get('basis') not in BASES:
                errors.append('科研卡片 '+field+' 缺正文或归属类型')
            errors.extend(evidence_errors(item.get('evidence', []), paragraphs, '科研卡片 '+field))
    if errors:
        raise ValueError('\n'.join(errors))
    pending = sum(r['status']=='needs_check' for r in records)
    return {'status': 'needs_check' if pending else 'reviewed', 'model_reviewed_paragraphs':len(records),
            'pending_paragraphs':pending, 'rule_flags':sum(len(r['flags']) for r in records),
            'visual_explanations':len(visuals), 'research_card_fields':len(CARD_FIELDS),
            'records':records, 'scope':'规则提示与模型第二轮审校分别记录；引文存在不等于已证明解读成立，不能保证无误。'}


def packet(data):
    return {'instructions':'逐段重新对照原文和译文，核对六类语义；修订后重新生成当前 digest。规则提示可能误报，逐项写理由；digest 不代表审校通过。',
            'paragraphs':[{'paragraph_id':p['id'], 'original':original_text(p,True),
                           'translation':p['translation'], 'analysis':p.get('analysis', []),
                           'digest':review_digest(p,data['glossary']), 'flags':flags_for(p,data['glossary'])}
                          for s in data['parts'] for p in s['paragraphs'] if p['kind']=='paragraph']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    args=parser.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8'))
    path=args.input.parent/'审校工作单.json'
    path.write_text(json.dumps(packet(data),ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(path.resolve()))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
