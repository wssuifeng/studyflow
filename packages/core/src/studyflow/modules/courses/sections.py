"""Bounded, non-executable concept sections; validation never infers teaching quality."""
def validate_sections(sections, where):
    from .content import obj,text,ident,sequence,invalid
    seen=set();budget=0
    def visit(items,loc,depth):
        nonlocal budget
        for i,item in enumerate(sequence(items,loc,1,40)):
            here=f"{loc}[{i}]"
            obj(item,here,{"id","title","role","body","summary","children"},{"id","title","role","body"})
            ident(item["id"],here+".id");text(item["title"],here+".title",200)
            if item["id"] in seen:invalid(here,"重复小节id")
            seen.add(item["id"])
            if len(seen)>40:invalid(where,"每块最多40个小节")
            if item["role"] not in ("main","supplement"):invalid(here,"小节角色仅main/supplement")
            text(item["body"],here+".body");budget+=len(item["body"])
            if item["role"]=="supplement" or "summary" in item:
                text(item.get("summary"),here+".summary",3000);budget+=len(item["summary"])
            if "children" in item:
                if depth>=2:invalid(here,"小节最多两层")
                visit(item["children"],here+".children",depth+1)
        if budget>20000:invalid(where,"摘要和正文合计最多20000字符")
    visit(sections,where,1)


def render_sections(sections):
    from copy import deepcopy
    from studyflow.infrastructure.markdown import render_markdown
    result=deepcopy(sections)
    for item in result:
        item["body_html"]=render_markdown(item["body"])
        if "summary" in item:item["summary_html"]=render_markdown(item["summary"])
        if "children" in item:item["children"]=render_sections(item["children"])
    return result


def section_markdown(sections,level=3):
    result=[]
    for item in sections:
        result.extend(["#"*level+" "+item["title"],item.get("summary",""),item["body"]])
        result.extend(section_markdown(item.get("children",[]),level+1))
    return result


def find_section(sections,identifier):
    for section in sections:
        if section["id"]==identifier:return section
        found=find_section(section.get("children",[]),identifier)
        if found:return found
    return None
