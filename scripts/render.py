"""Validate a model-completed reading.json and render a portable offline reader."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlparse
import xml.etree.ElementTree as ET
from audit import check_v2, CHECKS, CARD_FIELDS

ASSETS = Path(__file__).resolve().parents[1]/'assets'
TOKEN = re.compile(r'\[\[([MCN]\d+)\]\]')
IDENT = re.compile(r'[A-Za-z][A-Za-z0-9_-]*\Z')
E = html.escape
MATH_TAGS = set('math semantics mrow mi mn mo mtext mspace ms mfrac msqrt mroot mstyle merror mpadded mphantom mfenced menclose msub msup msubsup munder mover munderover mmultiscripts mprescripts none mtable mtr mtd mlabeledtr'.split())
MATH_ATTRS = set('display mathvariant stretchy fence separator form accent accentunder columnalign rowalign columnspan rowspan columnspacing rowspacing linethickness notation open close separators'.split())


def local_file(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('文件须使用阅读包内的相对路径。')
    path = (root/name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('文件不存在或超出阅读包：'+name)
    return path


def mathml(value):
    root = ET.fromstring(value)
    def clean(el):
        tag = el.tag.split('}')[-1] if isinstance(el.tag, str) else ''
        if tag not in MATH_TAGS:
            return None
        node = ET.Element(tag, {k: v for k,v in el.attrib.items() if k in MATH_ATTRS})
        node.text = el.text
        node.tail = el.tail
        for child in el:
            safe = clean(child)
            if safe is not None:
                node.append(safe)
        return node
    safe = clean(root)
    if safe is None or safe.tag != 'math':
        raise ValueError('结构化公式的根元素必须为 math。')
    return ET.tostring(safe, encoding='unicode')


def image_uri(root, name):
    path = local_file(root, name)
    types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif'}
    if path.suffix.lower() not in types:
        raise ValueError('公式图片仅支持 PNG、JPEG、WebP、GIF。')
    return 'data:'+types[path.suffix.lower()]+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')


def validate(data, root):
    errors = []
    def need(yes, text):
        if not yes:
            errors.append(text)
    def filled(value):
        return isinstance(value,str) and bool(value.strip()) and not re.fullmatch(r'TODO|TBD|待翻译|待补充|待解读', value.strip(), re.I)
    need(data.get('schema_version') in (1,2), 'schema_version 必须为 1 或 2')
    need(filled(data.get('title')), '缺少文章标题')
    source = data.get('source', {})
    try:
        file = local_file(root, source.get('file'))
        need(hashlib.sha256(file.read_bytes()).hexdigest()==source.get('sha256'), '原文哈希不符，核对来源或版本')
    except ValueError as exc:
        errors.append(str(exc))
    if source.get('url'):
        need(urlparse(source['url']).scheme in ('http','https'), '来源 URL 仅支持 http/https')
    glossary = data.get('glossary', [])
    term_ids = [t.get('id') for t in glossary]
    need(len(term_ids)==len(set(term_ids)), '术语 ID 重复')
    for t in glossary:
        need(bool(IDENT.fullmatch(str(t.get('id','')))), '术语 ID 格式错误')
        need(all(filled(t.get(k)) for k in ('term','translation','explanation')), '术语名称、中文及解释不能空白')
        for key in ('aliases_en','aliases_zh','avoid_zh'):
            need(isinstance(t.get(key,[]),list) and all(filled(x) for x in t.get(key,[])), '术语别名及排除译法须为字符串列表')
    overview = data.get('overview', [])
    need(bool(overview), '缺少文章整体解读 overview')
    for item in overview:
        need(filled(item.get('title')) and filled(item.get('text')), '整体解读存在空白项')
    parts = data.get('parts', [])
    need(bool(parts), '文章没有章节')
    all_ids = []
    coverage = []
    prose = 0
    for part in parts:
        all_ids.append(part.get('id'))
        units = part.get('paragraphs', [])
        if any(p.get('kind')=='paragraph' for p in units):
            need(filled(part.get('title_zh')) and filled(part.get('guide')), f'{part.get("id")} 缺中文标题或导读')
        for p in units:
            pid = p.get('id')
            all_ids.append(pid)
            need(filled(p.get('original')), f'{pid} 缺原文')
            need(p.get('kind') in ('paragraph','reference'), f'{pid} kind 必须为 paragraph 或 reference')
            need(bool(p.get('source_ids')), f'{pid} 缺少 source_ids')
            coverage.extend(p.get('source_ids', []))
            need(all(isinstance(n,int) and n>0 for n in p.get('pages',[])), f'{pid} 页码须为正整数')
            if p.get('kind')=='paragraph':
                prose += 1
                need(filled(p.get('translation')), f'{pid} 未完成翻译')
                need(filled(p.get('explanation')), f'{pid} 未完成段落解读')
            need(set(p.get('terms',[]))<=set(term_ids), f'{pid} 引用了不存在的术语')
            refs = p.get('protected', {})
            for field in ('original','translation'):
                need(set(TOKEN.findall(p.get(field,'') or ''))<=set(refs), f'{pid} {field} 存在未定义的公式/引文标记')
            for key, ref in refs.items():
                need(bool(re.fullmatch(r'[MCN]\d+', key)), f'{pid} 保护标记格式错误')
                need(ref.get('kind') in ('math','citation','name'), f'{pid} 保护项类型错误')
                try:
                    if ref.get('mathml'): mathml(ref['mathml'])
                    if ref.get('image'): image_uri(root, ref['image'])
                except (ValueError, ET.ParseError) as exc:
                    errors.append(f'{pid} 公式资源错误：{exc}')
    if data.get('schema_version')==2:
        all_ids.extend(v.get('id') for v in data.get('visuals',[]))
        all_ids.extend('review-'+p['id'] for s in parts for p in s['paragraphs'] if p['kind']=='paragraph')
        for v in data.get('visuals',[]):
            try:
                if v.get('image'): image_uri(root,v['image'])
            except ValueError as exc:
                errors.append(str(exc))
            need(all(isinstance(n,int) and n>0 for n in v.get('pages',[])), '图表页码须为正整数')
    need(prose>0, '没有叙述段落可生成精读版')
    need(all(IDENT.fullmatch(str(i or '')) for i in all_ids), '章节/段落 ID 格式错误')
    need(len(all_ids)==len(set(all_ids)), '章节或段落 ID 重复')
    need(not (set(all_ids) & {'overview','glossary','source-notes','search','mode','notes','topbtn','search-status','visuals','research-card','audit-report'}), '章节或段落 ID 与页面控件冲突')
    need(len(coverage)==len(set(coverage)), 'source_ids 被重复覆盖')
    try:
        baseline = json.loads((root/'source.json').read_text(encoding='utf-8'))
        expected = {p['id'] for s in baseline['parts'] for p in s['paragraphs']}
        need(set(coverage)==expected, f'来源覆盖不完整：缺 {len(expected-set(coverage))} 段，多 {len(set(coverage)-expected)} 段')
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        errors.append('缺少有效的 source.json 基线：'+str(exc))
    if errors:
        raise ValueError('\n'.join(errors))
    report = {'status': 'passed', 'prose_paragraphs': prose,
            'reference_units': sum(p['kind']=='reference' for s in parts for p in s['paragraphs']),
            'source_units_covered': len(coverage), 'terms': len(glossary),
            'source_sha256_verified': True,
            'scope': '结构、原文引文锚点、规则提示和模型审校记录检查；不保证语义无误，不等同于人工审校'}
    if data.get('schema_version')==2:
        report['review']=check_v2(data)
        if report['review']['pending_paragraphs']:
            report['status']='passed_with_pending_review'
    else:
        report['review']={'status':'legacy_not_reviewed','scope':'旧版数据，仅结构检查，尚无第二轮审校记录'}
    return report


def text_html(value):
    return E(value).replace('\n', '<br>')


def original_math(ref, root):
    if ref.get('image'):
        return '<img class="formula-image" alt="原文数学表达" src="'+image_uri(root, ref['image'])+'">'
    if ref.get('mathml'):
        return mathml(ref['mathml'])
    return '<code class="formula-text">'+E(ref.get('text',''))+'</code>'


def paragraph_text(value, refs):
    def replace(match):
        key = match[1]
        ref = refs[key]
        if ref['kind']=='math':
            return '<span class="long-math" title="原式在本段下方独立保留">〔式 '+E(key)+'〕</span>'
        return '<span class="citation">'+E(ref['text'])+'</span>' if ref['kind']=='citation' else E(ref['text'])
    return TOKEN.sub(replace, text_html(value))


BASIS={'author':'论文内容','analogy':'辅助类比','inference':'延伸推论','reader_note':'阅读提示'}
CHECK_LABELS=dict(zip(CHECKS,('语义忠实','否定关系','条件限定','数字与单位','术语一致','主张与证据')))
CARD_LABELS=dict(zip(CARD_FIELDS,('研究问题','真正贡献','关键假设','实验与论据','局限与失败条件','数据与复现成本','研究衔接与可验证想法')))


def evidence_html(items):
    if not items:return ''
    return '<details class="evidence"><summary>查看原文依据</summary>'+''.join(
        '<blockquote><a href="#'+E(x['paragraph_id'])+'">'+E(x['paragraph_id'])+' ↗</a><br>'+text_html(x['quote'])+'</blockquote>' for x in items)+'</details>'


def analysis_html(p):
    return ''.join('<div class="analysis-block"><div class="analysis-label">'+E(x['label'])+
        '<span class="basis">'+E(BASIS[x['basis']])+'</span></div><p>'+text_html(x['text'])+'</p>'+evidence_html(x.get('evidence',[]))+'</div>' for x in p.get('analysis',[]))


def review_html(p):
    r=p.get('review',{})
    if not r:return ''
    changes=''.join('<div class="revision"><div>修订前</div><del>'+text_html(x['before'])+'</del><div>修订后</div><ins>'+text_html(x['after'])+'</ins><p>'+text_html(x['reason'])+'</p><blockquote>'+text_html(x['source_quote'])+'</blockquote></div>' for x in r.get('changes',[]))
    decisions=''.join('<p><span class="review-state">'+('待核对' if x['resolution']=='open' else '提示已解释')+'</span> '+text_html(x['reason'])+'</p>' for x in r.get('decisions',[]))
    checks=''.join('<dt>'+E(CHECK_LABELS[k])+'</dt><dd>'+text_html(r.get('checklist',{}).get(k,''))+'</dd>' for k in CHECKS)
    return '<details class="review-block" id="review-'+E(p['id'])+'"><summary>查看第二轮审校记录（模型辅助）</summary><dl>'+checks+'</dl>'+decisions+changes+'</details>'


def enhanced_sections(data,root,report):
    paragraphs={p['id']:p for s in data['parts'] for p in s['paragraphs']}
    source=quote(data['source']['file'])
    blocks=[]
    if data.get('visuals'):
        cards=[]
        for v in data['visuals']:
            originals=[]
            for pid in v['paragraph_ids']:
                p=paragraphs[pid]
                if v.get('protected_key'):
                    originals.append(original_math(p['protected'][v['protected_key']],root))
            if v.get('image'):
                originals.append('<img class="formula-image" alt="原文图表" src="'+image_uri(root,v['image'])+'">')
            pages=v.get('pages') or paragraphs[v['paragraph_ids'][0]].get('pages',[])
            link=source+('#page='+str(min(pages)) if pages and data['source']['file'].lower().endswith('.pdf') else '')
            details=''.join('<h4>'+E(x['label'])+'</h4><p>'+text_html(x['text'])+'</p>' for x in v['details'])
            cards.append('<article class="visual-card" id="'+E(v['id'])+'"><h3>'+E(v['title'])+'</h3><div class="visual-original">'+''.join(originals)+'</div><p>'+text_html(v['summary'])+'</p>'+details+evidence_html(v['evidence'])+'<a href="'+link+'">核对原文图表 / 公式 ↗</a></article>')
        blocks.append('<section class="part" id="visuals"><div class="part-head"><div class="eyebrow">FIGURES & EQUATIONS</div><h2>图表与公式精读</h2></div><div class="paper-guide">'+''.join(cards)+'</div></section>')
    card=data['research_card']
    content=''.join('<h3>'+E(CARD_LABELS[field])+'</h3>'+''.join('<div class="research-item"><span class="basis">'+E(BASIS[x['basis']])+'</span><p>'+text_html(x['text'])+'</p>'+evidence_html(x['evidence'])+'</div>' for x in card[field]) for field in CARD_FIELDS)
    focus='<p>研究关注：'+E(data['research_focus'])+'</p>' if data.get('research_focus') else ''
    blocks.append('<section class="part" id="research-card"><div class="part-head"><div class="eyebrow">RESEARCH CARD</div><h2>科研视角阅读卡片</h2>'+focus+'</div><div class="paper-guide">'+content+'</div></section>')
    rows=''.join('<tr><td><a href="#review-'+E(x['paragraph_id'])+'">'+E(x['paragraph_id'])+'</a></td><td>'+('待核对' if x['status']=='needs_check' else '已做二轮模型审校')+'</td><td>'+str(len(x['flags']))+'</td></tr>' for x in report['records'])
    summary=f'第二轮检查 {report["model_reviewed_paragraphs"]} 段，待核对 {report["pending_paragraphs"]} 段，规则提示 {report["rule_flags"]} 项。'
    blocks.append('<section class="part" id="audit-report"><div class="part-head"><div class="eyebrow">REVIEW RECORD</div><h2>翻译与解读审校</h2></div><div class="paper-guide"><p>'+summary+'</p><p>规则提示只用于发现可疑差异；语义由模型第二轮对照审校。原文引文已检查可定位，不等于解读已被自动证明。</p><details><summary>查看逐段记录索引</summary><table><tr><th>段落</th><th>审校状态</th><th>规则提示数</th></tr>'+rows+'</table></details><p><a href="审校报告.json">下载详细审校报告</a></p></div></section>')
    return ''.join(blocks)


def render(data, root):
    glossary = {t['id']: t for t in data['glossary']}
    source = quote(data['source']['file'])
    toc, body = [], []
    enhanced=data.get('schema_version')==2
    review_report=check_v2(data) if enhanced else None
    for n, part in enumerate((s for s in data['parts'] if s['paragraphs']), 1):
        title = part.get('title_zh') or part['title']
        sub = ' class="sub"' if part.get('level',2)>2 else ''
        toc.append(f'<a{sub} href="#{E(part["id"])}">{E(title)}</a>')
        body.append(f'<section class="part article-part" id="{E(part["id"])}"><div class="part-head"><div class="eyebrow">PART {n:02d}</div><h2>{E(title)}</h2><div class="section-en">{E(part["title"])}</div></div>')
        if part.get('guide'):
            body.append('<div class="part-guide"><strong>本 Part 导读</strong><br>'+text_html(part['guide'])+'</div>')
        for i,p in enumerate(part['paragraphs'], 1):
            link = source + ('#page='+str(min(p['pages'])) if p.get('pages') and data['source']['file'].lower().endswith('.pdf') else '')
            refs = p.get('protected', {})
            original = paragraph_text(p['original'], refs)
            if p['kind']=='reference':
                body.append(f'<details class="reference" id="{E(p["id"])}"><summary>原文参考内容 · 公式 / 图表 / 元信息</summary><div>{original}</div><a href="{link}">核对原文 ↗</a></details>')
                if any(v['kind']=='math' for v in refs.values()):
                    body.append('<div class="equation">'+''.join(original_math(v,root) for v in refs.values() if v['kind']=='math')+'</div>')
                continue
            translation = paragraph_text(p['translation'], refs)
            terms = ''.join('<p><span class="term">'+E(glossary[t]['translation'])+' · '+E(glossary[t]['term'])+'</span>：'+text_html(glossary[t]['explanation'])+'</p>' for t in p.get('terms',[]))
            maths = [(k,v) for k,v in refs.items() if v['kind']=='math']
            math_html = ''
            if maths:
                math_html = '<details class="math-notes"><summary>查看本段原式（不参与翻译）</summary>'+''.join('<div class="math-item">'+E(k)+'：'+original_math(v,root)+'</div>' for k,v in maths)+f'<a href="{link}">核对原 PDF / 原文 ↗</a></details>'
            pages = ' · 原文页 '+', '.join(map(str,p['pages'])) if p.get('pages') else ''
            badge=''
            if enhanced:
                pending=p['review']['status']=='needs_check'
                badge='<a class="review-badge'+(' pending' if pending else '')+'" href="#review-'+E(p['id'])+'">'+('待核对' if pending else '二轮模型审校')+'</a>'
                linked=[v for v in data['visuals'] if p['id'] in v['paragraph_ids']]
                math_html+=''.join('<p class="visual-link"><a href="#'+E(v['id'])+'">'+E(v['title'])+' · 查看详细解读 ↗</a></p>' for v in linked)
            detailed=analysis_html(p) if enhanced else ''
            audit_block=review_html(p) if enhanced else ''
            body.append(f'<article class="paragraph" id="{E(p["id"])}"><div class="para-meta"><span>自然段 {i:02d}{E(pages)}</span><a href="#{E(p["id"])}">#</a><a href="{link}" target="_blank" rel="noopener">核对原文 ↗</a>{badge}</div><div class="pair"><div class="en"><div class="col-label">ORIGINAL</div>{original}</div><div class="zh"><div class="col-label">中文译文 / 整理</div>{translation}</div></div>{math_html}<div class="annotations"><div class="tag">段落解读 · 辅助说明</div><p>{text_html(p["explanation"])}</p>{detailed}{terms}</div>{audit_block}</article>')
        body.append('</section>')
    overview = ''.join('<h3>'+E(x['title'])+'</h3>'+('<span class="basis">'+E(BASIS[x['basis']])+'</span>' if enhanced else '')+'<p class="overview-text">'+text_html(x['text'])+'</p>'+evidence_html(x.get('evidence',[])) for x in data['overview'])
    body.append('<section class="part" id="overview"><div class="part-head"><div class="eyebrow">READING GUIDE</div><h2>整体通俗解读</h2></div><div class="paper-guide">'+overview+'</div></section>')
    if enhanced:
        body.append(enhanced_sections(data,root,review_report))
    if glossary:
        body.append('<section class="part glossary" id="glossary"><div class="part-head"><h2>专业术语速查</h2></div><dl>'+''.join('<dt>'+E(t['translation'])+' · '+E(t['term'])+'</dt><dd>'+text_html(t['explanation'])+'</dd>' for t in glossary.values())+'</dl></section>')
    notes = list(data.get('notes',[])) + list(data.get('warnings',[]))
    if data['source'].get('version'):
        notes.insert(0,'原文版本：'+data['source']['version'])
    note_html = ''.join('<p class="reading-note">'+text_html(t)+'</p>' for t in notes)
    if data['source'].get('url'):
        note_html += '<p><a href="'+E(data['source']['url'])+'">在线来源 ↗</a></p>'
    css = (ASSETS/'reader.css').read_text(encoding='utf-8')
    js = (ASSETS/'reader.js').read_text(encoding='utf-8')
    count = sum(p['kind']=='paragraph' for s in data['parts'] for p in s['paragraphs'])
    extra_links='<a href="#visuals">图表与公式精读</a>' if data.get('visuals') else ''
    if enhanced:extra_links+='<a href="#research-card">科研阅读卡片</a><a href="#audit-report">翻译与解读审校</a>'
    review_status=('<span>二轮审校 · 待核对 '+str(review_report['pending_paragraphs'])+' 段</span>') if enhanced else '<span>基础版 · 尚无二轮审校记录</span>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{E(data['title'])} · 论文精读</title><style>{css}</style></head><body>
<header class="top"><a class="brand" href="#">论文精读阅读器</a><div class="actions"><input id="search" type="search" placeholder="搜索正文与解释" aria-label="搜索正文与解释"><button id="mode" aria-pressed="false">仅看中文</button><button id="notes" class="active" aria-pressed="true">段落解读</button></div></header>
<div class="shell"><aside class="side"><h2>CONTENTS / 章节</h2><nav class="toc">{''.join(toc)}</nav><div class="side-links"><a href="#overview">整体通俗解读</a>{extra_links}<a href="#source-notes">版本与阅读说明</a><a href="{source}">原文 ↗</a></div></aside><main><div class="hero"><div class="eyebrow">CONTINUOUS READING EDITION</div><h1>{E(data['title'])}</h1><div class="meta"><span>{count} 个完整自然段</span><span>按 Part 组织</span><span>原文对照 · 术语解释</span>{review_status}</div><p>按章节连续阅读；翻译与辅助解读分开呈现，公式和人名保留原样。</p><details class="notice" id="source-notes"><summary>版本与阅读说明</summary>{note_html}<p>本页使用模型辅助翻译和解读；记录检查不等于全文人工审校，关键公式、数据和引用请核对原文。</p></details></div><p id="search-status" class="search-empty" role="status" hidden></p>{''.join(body)}<footer class="footer">论文及文章版权归原作者。此页面供研究阅读，术语和解读属于辅助说明。</footer></main></div><button id="topbtn" aria-label="回到顶部">↑</button><script>{js}</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    root = args.input.resolve().parent
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        report = validate(data,root)
        if not args.check_only:
            page = render(data,root)
            (root/'论文精读.html').write_text(page,encoding='utf-8')
            (root/'检查报告.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            if data.get('schema_version')==2:
                (root/'审校报告.json').write_text(json.dumps(report['review'],ensure_ascii=False,indent=2),encoding='utf-8')
        summary={**report,'review':{k:v for k,v in report['review'].items() if k!='records'}}
        print(json.dumps(summary,ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, '未生成成品：'+str(exc)+'\n')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
