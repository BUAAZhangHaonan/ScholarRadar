"""Private, readable copies of the two isolated acceptance examples."""
from html import escape
import json
from fastapi import APIRouter,HTTPException
from fastapi.responses import HTMLResponse
from .settings import VAR

router=APIRouter()
CASES={"cross-day":"refactor-crossday.json","feedback":"refactor-feedback-demo.json"}


def data_for(slug):
    path=VAR/"acceptance"/CASES.get(slug,"not-a-case")
    if slug not in CASES or not path.is_file(): raise HTTPException(404,"示例尚未生成")
    return json.loads(path.read_text())


def text(value):
    return escape(str(value or ""))


def link(wid,title):
    return '<a href="/works/'+escape(wid,quote=True)+'">'+text(title)+'</a>'


@router.get("/api/research-examples/{slug}")
def example(slug:str): return data_for(slug)


@router.get("/research-examples/{slug}",response_class=HTMLResponse)
def case_page(slug:str):
    d=data_for(slug)
    if slug=="cross-day":
        title="两篇论文怎样改变同一个判断"
        intro=d["environment"]
        parts=[]
        for paper in d["papers"]:
            parts.append('<li>'+link(paper["work_id"],paper["title"])+' · '+text(paper["version"])+' · '+text(paper["publication_date"])+'</li>')
        body=('<h2>第一天只留下一条阅读记录</h2><p>'+text(d["day_one"]["retained_understanding"])+'</p>'
              '<h2>第二天找回了哪条证据</h2><p>'+text(d["day_two"]["change"])+'</p><p>'+text(d["day_two"]["judgment"])+'</p>'
              '<h2>下一步可区分的解释</h2><p>'+text(d["alternative_explanations"])+'</p><ul>'+''.join(parts)+'</ul>')
    else:
        title="一条反馈如何改变下一次选择"
        intro="这是隔离副本里的演练。两次筛选采用相同的五篇实际论文，示例评价没有写入个人反馈。"
        before=d["before"];after=d["after"];f=d["example_input"]
        body=('<h2>原先选中的论文</h2><p>'+link(before["work_id"],before["title"])+'</p><p>'+text(before["why"])+'</p>'
              '<h2>本次演练输入</h2><p>'+text(f["reason"])+'</p><h2>相同候选集的下一次选择</h2><p>'+
              link(after["work_id"],after["title"])+'</p><p>'+text(after["why"])+'</p>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>'+text(title)+' · ScholarRadar</title><link rel="stylesheet" href="/static/site.css">'
            '<main class="shell"><a href="/">返回研究动态</a><article class="reading"><h1>'+text(title)+'</h1><p>'+text(intro)+'</p>'+body+'</article></main></html>')
